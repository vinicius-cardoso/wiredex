"""The build lifecycle routes over the in-memory fakes: a bare FastAPI, no database.

What is asserted here is the router's own contract (decision 13): every route's status, the
body each refusal in the design's error table answers with its code and fields, and the shapes
on the wire the web builds on. The transitions and reads themselves are the use-case tests'
(test_lifecycle_use_cases.py); here they are driven only far enough to see the wire.
"""

from typing import Any, get_args
from uuid import uuid7

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from support.projects import BENCH, World
from wiredex.projects.api.router import create_router
from wiredex.projects.api.schemas import RefusalCode, TransitionName
from wiredex.projects.domain.bom import BomLine, LineContent
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.lifecycle import (
    EmptyBomError,
    RepeatedUnitError,
    ShortError,
    StockChangedError,
    TooManyUnitsError,
    Transition,
    TransitionNotAllowedError,
    UnitNotInStockError,
    UnitNotNeededError,
    UnknownLocationError,
    UnknownUnitError,
)
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.values import (
    BomLineId,
    LocationId,
    PartId,
    WorkspaceId,
)

MADE_UP = "0199aaaa-0000-7000-8000-000000000000"
DRAWER = LocationId(uuid7())


async def the_bench(_request: Request) -> WorkspaceId:
    """What `bootstrap/app.py` builds from the session: the workspace this request acts in."""
    return BENCH


class Bench:
    """*Weather station* with a draft revision A, a BOM of one ESP32 board and three 10k, the
    catalog and the stock to cover it, and a client mounting the router over the fakes."""

    def __init__(self, *, resistor_on_hand: int = 40, esp32_on_hand: int = 1) -> None:
        self.world = World()
        self.project: Project = self.world.hold_project("Weather station")
        (revision,) = self.world.work.revisions.saved.values()
        self.revision = revision
        self.sibling = self.world.hold_revision(self.project, "B", minutes=1)

        self.esp32 = self.world.build_parts.hold("ESP32", tracked=True)
        self.resistor = self.world.build_parts.hold("Resistor 10k")
        self._line(self.esp32, 1)
        self._line(self.resistor, 3)

        codes = ["WX-U-0001"] if esp32_on_hand else []
        self.world.build_stock.hold_lot(
            self.esp32,
            location_id=DRAWER,
            location_code="WX-L-0004",
            on_hand=esp32_on_hand,
            units=codes,
        )
        self.world.build_stock.hold_lot(
            self.resistor, location_id=DRAWER, location_code="WX-L-0003", on_hand=resistor_on_hand
        )

        app = FastAPI()
        app.include_router(create_router(self.world.projects_use_cases(), the_bench), prefix="/api")
        self.client = TestClient(app)

    def _line(self, part_id: PartId, quantity: int) -> None:
        line = BomLine(
            BomLineId(uuid7()),
            BENCH,
            self.revision.id,
            LineContent.of(part_id, Designators.none(), quantity, None),
            self.world.clock.now(),
        )
        self.world.work.bom_lines.saved[line.id] = line

    def path(self, tail: str, revision: Any | None = None) -> str:
        return f"/api/projects/revisions/{(revision or self.revision).id}/{tail}"

    def board(self) -> str:
        return str(self.world.build_stock.unit("WX-U-0001").unit_id)

    async def reserve(self) -> None:
        await self.world.reserve_revision(BENCH, self.revision.id, [])

    async def build(self) -> None:
        await self.world.build_revision(BENCH, self.revision.id)

    async def dismantle(self) -> None:
        await self.world.dismantle_revision(BENCH, self.revision.id, DRAWER)


@pytest.fixture
def bench() -> Bench:
    return Bench()


def refusal(response: Any) -> dict[str, Any]:
    detail: dict[str, Any] = response.json()["detail"]
    return detail


# --- The transitions ------------------------------------------------------------------------


def test_reserve_sets_the_stock_aside_and_answers_the_revision(bench: Bench) -> None:
    # Requirement 2: a draft's parts set aside, the revision answered reserved.
    response = bench.client.post(bench.path("reserve"), json={"units": []})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["id"], body["status"]) == (str(bench.revision.id), "reserved")
    assert bench.world.work.commits == 1


def test_reserve_may_name_a_unit(bench: Bench) -> None:
    # Requirement 3.2: the owner picks the board.
    response = bench.client.post(bench.path("reserve"), json={"units": [bench.board()]})

    assert response.status_code == 200, response.text
    assert bench.world.build_stock.unit("WX-U-0001").status == "reserved"


def test_reserve_defaults_to_no_named_units(bench: Bench) -> None:
    # An empty body is the same as {"units": []}: the automatic choice (decision 13).
    response = bench.client.post(bench.path("reserve"), json={})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "reserved"


@pytest.mark.anyio
async def test_cancel_returns_a_reservation_to_draft(bench: Bench) -> None:
    await bench.reserve()

    response = bench.client.post(bench.path("cancel"))

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "draft"


@pytest.mark.anyio
async def test_build_consumes_a_reservation(bench: Bench) -> None:
    await bench.reserve()

    response = bench.client.post(bench.path("build"))

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "built"


@pytest.mark.anyio
async def test_dismantle_returns_the_build_to_a_location(bench: Bench) -> None:
    await bench.reserve()
    await bench.build()

    response = bench.client.post(bench.path("dismantle"), json={"location_id": str(DRAWER)})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "dismantled"


# --- Refusals: the design's error table -----------------------------------------------------


def test_a_transition_the_status_forbids_is_a_409(bench: Bench) -> None:
    # Requirement 1.2: a build of a draft, refused naming the status and the transition.
    response = bench.client.post(bench.path("build"))

    assert response.status_code == 409
    detail = refusal(response)
    assert (detail["code"], detail["transition"], detail["status"]) == (
        "transition_not_allowed",
        "build",
        "draft",
    )
    assert bench.world.work.commits == 0


def test_a_short_reserve_is_a_409_with_its_report() -> None:
    # Requirements 2.1, 2.2: the report names each short part.
    short = Bench(resistor_on_hand=1)

    response = short.client.post(short.path("reserve"), json={"units": []})

    assert response.status_code == 409
    detail = refusal(response)
    assert (detail["code"], detail["transition"]) == ("short", "reserve")
    assert detail["report"]["summary"]["short_parts"] == 1
    assert short.world.work.commits == 0


def test_an_empty_bom_reserve_is_a_409(bench: Bench) -> None:
    # Requirement 2.3.
    bench.world.work.bom_lines.saved.clear()

    response = bench.client.post(bench.path("reserve"), json={"units": []})

    assert response.status_code == 409
    assert refusal(response)["code"] == "empty_bom"


def test_a_named_unit_the_workspace_doesnt_hold_is_a_422(bench: Bench) -> None:
    # Requirements 3.4, 11.2: another workspace's unit looks unknown, and its 422 names it.
    made_up = str(uuid7())

    response = bench.client.post(bench.path("reserve"), json={"units": [made_up]})

    assert response.status_code == 422
    detail = refusal(response)
    assert (detail["code"], detail["transition"]) == ("unknown_unit", "reserve")
    assert detail["unit_id"] == made_up
    assert detail["unit_code"] is None
    assert bench.world.work.commits == 0


def test_a_unit_named_twice_is_a_422_naming_it(bench: Bench) -> None:
    # Requirement 3.4. The repeated check runs before the unit is confirmed held, so it names
    # the id but not the code (the code is filled only once the workspace is known to hold it).
    board = bench.board()

    response = bench.client.post(bench.path("reserve"), json={"units": [board, board]})

    assert response.status_code == 422
    detail = refusal(response)
    assert detail["code"] == "repeated_unit"
    assert detail["unit_id"] == board


def test_stock_changed_is_a_409(bench: Bench) -> None:
    # Decision 12: a receipt between the two locks.
    bench.world.build_stock.next_changed = True

    response = bench.client.post(bench.path("reserve"), json={"units": []})

    assert response.status_code == 409
    assert refusal(response)["code"] == "stock_changed"


@pytest.mark.parametrize("tail", ["reserve", "cancel", "build", "dismantle"])
def test_a_transition_of_a_revision_that_doesnt_exist_is_404(bench: Bench, tail: str) -> None:
    # Requirements 1.7, 11.3: another workspace's revision is 404, not 403.
    body: dict[str, Any] = {"units": []} if tail == "reserve" else {"location_id": str(DRAWER)}
    response = bench.client.post(f"/api/projects/revisions/{MADE_UP}/{tail}", json=body)

    assert response.status_code == 404
    assert response.json()["detail"] == "that revision doesn't exist"


def test_more_than_100_named_units_is_the_schemas_own_422(bench: Bench) -> None:
    # Decision 13: a 101st unit gets FastAPI's own 422, which carries no code.
    units = [str(uuid7()) for _ in range(101)]

    response = bench.client.post(bench.path("reserve"), json={"units": units})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_a_dismantle_without_a_location_is_the_schemas_own_422(bench: Bench) -> None:
    response = bench.client.post(bench.path("dismantle"), json={})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


# --- The reads ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_lifecycle_read_answers_status_transitions_and_what_it_holds(
    bench: Bench,
) -> None:
    # Requirement 10.1.
    await bench.reserve()

    response = bench.client.get(bench.path("lifecycle"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "reserved"
    assert body["transitions"] == ["cancel", "build"]
    assert body["deletable"] is False
    by_part = {part["part_id"]: part for part in body["parts"]}
    esp32 = by_part[str(bench.esp32)]
    assert esp32["part"]["name"] == "ESP32"
    assert [unit["code"] for unit in esp32["units"]] == ["WX-U-0001"]
    resistor = by_part[str(bench.resistor)]
    assert sum(location["quantity"] for location in resistor["reserved"]) == 3
    assert resistor["consumed"] == 0


def test_the_lifecycle_read_of_a_draft_holds_nothing_and_can_be_deleted(bench: Bench) -> None:
    response = bench.client.get(bench.path("lifecycle"))

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["transitions"], body["deletable"], body["parts"]) == (
        "draft",
        ["reserve"],
        True,
        [],
    )


@pytest.mark.anyio
async def test_a_built_revisions_units_answer_no_location(bench: Bench) -> None:
    # Requirement 3.10: a unit in use sits on a board, not in a drawer.
    await bench.reserve()
    await bench.build()

    body = bench.client.get(bench.path("lifecycle")).json()

    by_part = {part["part_id"]: part for part in body["parts"]}
    [unit] = by_part[str(bench.esp32)]["units"]
    assert unit["location_code"] is None


def test_the_lifecycle_read_of_a_revision_that_doesnt_exist_is_404(bench: Bench) -> None:
    response = bench.client.get(f"/api/projects/revisions/{MADE_UP}/lifecycle")

    assert response.status_code == 404
    assert response.json()["detail"] == "that revision doesn't exist"


def test_a_revision_is_found_by_its_id_alone(bench: Bench) -> None:
    # Requirement 10.2.
    response = bench.client.get(f"/api/projects/revisions/{bench.revision.id}")

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["label"], body["status"]) == (
        str(bench.revision.id),
        "A",
        "draft",
    )
    assert (body["project_id"], body["project_name"]) == (
        str(bench.project.id),
        "Weather station",
    )


def test_a_revision_ref_of_a_revision_that_doesnt_exist_is_404(bench: Bench) -> None:
    response = bench.client.get(f"/api/projects/revisions/{MADE_UP}")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_a_parts_holdings_name_each_revision_holding_it(bench: Bench) -> None:
    # Requirement 10.4.
    await bench.reserve()

    response = bench.client.get(f"/api/projects/parts/{bench.resistor}/holdings")

    assert response.status_code == 200
    [holding] = response.json()
    assert holding["revision"]["id"] == str(bench.revision.id)
    assert (holding["reserved"], holding["consumed"]) == (3, 0)


def test_a_parts_holdings_are_empty_when_nothing_holds_it(bench: Bench) -> None:
    response = bench.client.get(f"/api/projects/parts/{bench.resistor}/holdings")

    assert response.status_code == 200
    assert response.json() == []


# --- The wire contract ----------------------------------------------------------------------


def test_the_wire_names_match_their_enums() -> None:
    # A new transition or refusal code stops type-checking in the schemas; this catches a name
    # listed in the union that its source doesn't have.
    codes = {
        error.code
        for error in (
            TransitionNotAllowedError,
            EmptyBomError,
            ShortError,
            UnknownUnitError,
            RepeatedUnitError,
            UnitNotNeededError,
            TooManyUnitsError,
            UnitNotInStockError,
            UnknownLocationError,
            StockChangedError,
        )
    }
    assert set(get_args(TransitionName.__value__)) == {t.value for t in Transition}
    assert set(get_args(RefusalCode.__value__)) == codes
