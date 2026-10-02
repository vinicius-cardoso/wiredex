"""The dashboard's projects routes over the in-memory fakes: a bare FastAPI, no database.

What is asserted here is the router's contract (18-dashboard's HTTP table): the shapes on the
wire, the limit and its 422, and the static paths answered before `/{project_id}` would take
them as an id. The reads themselves are the use-case tests' (test_dashboard_use_cases.py).
"""

from uuid import uuid7

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from support.projects import BENCH, NOW, World
from wiredex.projects.api.router import create_router
from wiredex.projects.domain.bom import BomLine, LineContent
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.values import BomLineId, LocationId, PartId, RevisionId, WorkspaceId

DRAWER = LocationId(uuid7())


async def the_bench(_request: Request) -> WorkspaceId:
    """What `bootstrap/app.py` builds from the session: the workspace this request acts in."""
    return BENCH


class Bench:
    """*Weather station* A reserving three 10k and two 100n, and *Robot* A built with five
    10k, with a client mounting the router over the fakes."""

    def __init__(self) -> None:
        self.world = World()
        self.resistor = self._part("Resistor 10k")
        self.capacitor = self._part("Capacitor 100n")
        self.station = self._draft("Weather station", {self.resistor: 3, self.capacitor: 2})
        self.robot = self._draft("Robot", {self.resistor: 5})
        app = FastAPI()
        app.include_router(create_router(self.world.projects_use_cases(), the_bench), prefix="/api")
        self.client = TestClient(app)

    async def hold(self) -> None:
        await self.world.reserve_revision(BENCH, self.station, [])
        await self.world.reserve_revision(BENCH, self.robot, [])
        await self.world.build_revision(BENCH, self.robot)

    def _part(self, name: str) -> PartId:
        # The same part to the build's ports and to the BOM's, 50 of it in stock.
        part_id = self.world.build_parts.hold(name)
        self.world.build_stock.hold_lot(
            part_id, location_id=DRAWER, location_code="WX-L-0001", on_hand=50
        )
        self.world.parts.facts[part_id] = self.world.build_parts.facts[part_id]
        self.world.stock.available_by_part[part_id] = 50
        return part_id

    def _draft(self, name: str, lines: dict[PartId, int]) -> RevisionId:
        project = self.world.hold_project(name, revision=None)
        revision = self.world.hold_revision(project, "A")
        for part_id, quantity in lines.items():
            line = BomLine(
                BomLineId(uuid7()),
                BENCH,
                revision.id,
                LineContent.of(part_id, Designators.none(), quantity, None),
                NOW,
            )
            self.world.work.bom_lines.saved[line.id] = line
        return revision.id


@pytest.fixture
def bench() -> Bench:
    return Bench()


@pytest.mark.anyio
async def test_the_tied_up_parts_answer_each_part_and_its_revisions(bench: Bench) -> None:
    # Requirements 1.1 and 1.2, on the wire.
    await bench.hold()

    response = bench.client.get("/api/projects/holdings")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["more"] == 0
    resistor, capacitor = body["parts"]
    assert resistor["part_id"] == str(bench.resistor)
    assert resistor["part"]["name"] == "Resistor 10k"
    assert (resistor["reserved"], resistor["consumed"]) == (3, 5)
    assert [
        (holding["revision"]["project_name"], holding["revision"]["status"], holding["consumed"])
        for holding in resistor["revisions"]
    ] == [("Robot", "built", 5), ("Weather station", "reserved", 0)]
    assert resistor["revisions"][1]["revision"]["id"] == str(bench.station)
    assert (capacitor["part_id"], capacitor["reserved"]) == (str(bench.capacitor), 2)


@pytest.mark.anyio
async def test_a_limit_answers_that_many_and_counts_the_rest(bench: Bench) -> None:
    # Requirement 1.3.
    await bench.hold()

    response = bench.client.get("/api/projects/holdings", params={"limit": 1})

    assert response.status_code == 200
    body = response.json()
    assert [part["part_id"] for part in body["parts"]] == [str(bench.resistor)]
    assert body["more"] == 1


def test_nothing_tied_up_answers_an_empty_page(bench: Bench) -> None:
    response = bench.client.get("/api/projects/holdings")

    assert response.status_code == 200
    assert response.json() == {"parts": [], "more": 0}


@pytest.mark.parametrize("limit", [0, 101, -1])
def test_a_limit_outside_one_to_a_hundred_is_refused(bench: Bench, limit: int) -> None:
    # Requirement 1.3: FastAPI's own 422, before the use case runs.
    response = bench.client.get("/api/projects/holdings", params={"limit": limit})

    assert response.status_code == 422
    assert bench.world.build_stock.holdings_reads == 0


def test_the_shortages_answer_each_short_draft_and_its_missing_parts(bench: Bench) -> None:
    # Requirement 2.1, on the wire: one capacitor in stock for a draft needing two; the
    # robot's five resistors are covered, so it is left out.
    bench.world.stock.available_by_part[bench.capacitor] = 1

    response = bench.client.get("/api/projects/shortages")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["more"] == 0
    [station] = body["revisions"]
    assert station["revision"]["id"] == str(bench.station)
    assert (station["revision"]["project_name"], station["revision"]["label"]) == (
        "Weather station",
        "A",
    )
    assert (station["summary"]["short_parts"], station["summary"]["complete"]) == (1, False)
    [capacitor] = station["parts"]
    assert capacitor["part_id"] == str(bench.capacitor)
    assert capacitor["part"]["name"] == "Capacitor 100n"
    assert (capacitor["need"], capacitor["available"], capacitor["short"]) == (2, 1, 1)
    assert capacitor["status"] == "short"


def test_a_shortages_limit_answers_that_many_and_counts_the_rest(bench: Bench) -> None:
    # Requirement 2.3: both drafts short, the first by project name answered.
    bench.world.stock.available_by_part[bench.resistor] = 0

    response = bench.client.get("/api/projects/shortages", params={"limit": 1})

    assert response.status_code == 200
    body = response.json()
    assert [found["revision"]["project_name"] for found in body["revisions"]] == ["Robot"]
    assert body["more"] == 1


def test_no_draft_short_answers_an_empty_page(bench: Bench) -> None:
    response = bench.client.get("/api/projects/shortages")

    assert response.status_code == 200
    assert response.json() == {"revisions": [], "more": 0}


@pytest.mark.parametrize("limit", [0, 101])
def test_a_shortages_limit_outside_one_to_a_hundred_is_refused(bench: Bench, limit: int) -> None:
    response = bench.client.get("/api/projects/shortages", params={"limit": limit})

    assert response.status_code == 422
    assert bench.world.parts.asked == []
