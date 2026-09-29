"""The BOM routes over the in-memory fakes: a bare FastAPI, no database.

What is asserted here is the router's own contract: every route's status, the body each
refusal in the design's error table answers, with its code and field, and the shapes on the
wire the BOM editor builds on (design's HTTP API).
"""

from datetime import timedelta
from typing import Any, get_args
from uuid import uuid7

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from support.projects import BENCH, NOW, World
from wiredex.projects.api.router import create_router
from wiredex.projects.api.schemas import BomFieldName, BomRefusalCodeName, StockStatusName
from wiredex.projects.domain.bom import MAX_LINES, BomLine, LineContent
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.errors import BomField, ContentRefusal
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.shortage import StockStatus
from wiredex.projects.domain.values import BomLineId, PartId, RevisionStatus, WorkspaceId

MADE_UP = "0199aaaa-0000-7000-8000-000000000000"


async def the_bench(_request: Request) -> WorkspaceId:
    """What `bootstrap/app.py` builds from the session: the workspace this request acts in."""
    return BENCH


class Bench:
    """A world with a draft revision A, a resistor, a sensor and a wire in the catalog, and
    a client mounting the router over it."""

    def __init__(self) -> None:
        self.world = World()
        self.project: Project = self.world.hold_project("Weather station")
        self.revision = next(iter(self.world.work.revisions.saved.values()))
        self.resistor = self.world.parts.hold("Resistor 4k7 0805")
        self.sensor = self.world.parts.hold("BME280")
        self.wire = self.world.parts.hold("Hook-up wire 22 AWG", not_stocked=True)
        self.world.clock.advance(timedelta(hours=1))
        app = FastAPI()
        app.include_router(create_router(self.world.projects_use_cases(), the_bench), prefix="/api")
        self.client = TestClient(app)

    def bom(self, revision: Revision | None = None) -> str:
        return f"/api/projects/revisions/{(revision or self.revision).id}/bom"

    def lines(self, revision: Revision | None = None) -> str:
        return f"{self.bom(revision)}/lines"

    def hold_line(
        self, part_id: PartId, designators: str = "", quantity: int | None = None, minutes: int = 0
    ) -> BomLine:
        """A line written straight to the store, as a seed."""
        content = LineContent.of(part_id, Designators.parse(designators), quantity, None)
        line = BomLine.on(
            self.revision, BomLineId(uuid7()), content, NOW + timedelta(minutes=minutes)
        )
        self.world.work.bom_lines.saved[line.id] = line
        return line

    def locked(self, status: RevisionStatus = RevisionStatus.RESERVED) -> None:
        """Only 10-build-lifecycle moves a status; until then the tests place one."""
        self.revision.status = status

    def add(self, body: dict[str, Any]) -> dict[str, Any]:
        """POSTs a line that is expected to be added, so a test can get on with its point."""
        response = self.client.post(self.lines(), json=body)
        assert response.status_code == 201, response.text
        added: dict[str, Any] = response.json()
        return added


@pytest.fixture
def bench() -> Bench:
    return Bench()


def refusal(response: Any) -> dict[str, Any]:
    detail: dict[str, Any] = response.json()["detail"]
    return detail


# --- Reading ----------------------------------------------------------------------------------


def test_a_bom_answers_its_lines_its_report_and_that_a_draft_can_change(bench: Bench) -> None:
    # Requirements 4.11, 5.2, 6.1 and 6.6, in the shape the design's example gives.
    sensor = bench.hold_line(bench.sensor, "U2")
    bench.hold_line(bench.wire, quantity=1, minutes=1)

    response = bench.client.get(bench.bom())

    assert response.status_code == 200
    bom = response.json()
    assert (bom["revision_id"], bom["status"], bom["editable"]) == (
        str(bench.revision.id),
        "draft",
        True,
    )
    assert bom["lines"][0] == {
        "id": str(sensor.id),
        "revision_id": str(bench.revision.id),
        "part_id": str(bench.sensor),
        "designators": ["U2"],
        "designator_text": "U2",
        "quantity": 1,
        "notes": None,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    assert bom["report"]["summary"] == {
        "lines": 2,
        "parts": 2,
        "short_parts": 1,
        "short_pieces": 1,
        "not_stocked_parts": 1,
        "unknown_parts": 0,
        "complete": False,
    }
    short, wire = bom["report"]["parts"]
    assert short == {
        "part_id": str(bench.sensor),
        "lines": 1,
        "need": 1,
        "available": 0,
        "short": 1,
        "status": "short",
        "part": {
            "name": "BME280",
            "manufacturer": None,
            "mpn": None,
            "package": None,
            "tracked_individually": False,
            "not_stocked": False,
        },
    }
    assert (wire["status"], wire["available"], wire["short"]) == ("not_stocked", None, 0)
    assert wire["part"]["not_stocked"] is True


def test_a_covered_part_answers_its_available_stock(bench: Bench) -> None:
    bench.hold_line(bench.resistor, "R1-4")
    bench.world.stock.available_by_part[bench.resistor] = 180

    [part] = bench.client.get(bench.bom()).json()["report"]["parts"]

    assert (part["need"], part["available"], part["short"], part["status"]) == (
        4,
        180,
        0,
        "covered",
    )


def test_an_unknown_part_answers_no_facts_no_stock_and_none_short(bench: Bench) -> None:
    # Requirement 6.5: a part the catalog no longer holds.
    gone = PartId(uuid7())
    bench.hold_line(gone, "U9")

    bom = bench.client.get(bench.bom()).json()

    [part] = bom["report"]["parts"]
    assert part == {
        "part_id": str(gone),
        "lines": 1,
        "need": 1,
        "available": None,
        "short": 0,
        "status": "unknown_part",
        "part": None,
    }
    assert bom["report"]["summary"]["unknown_parts"] == 1
    assert bom["report"]["summary"]["complete"] is False


def test_an_empty_bom_is_complete(bench: Bench) -> None:
    bom = bench.client.get(bench.bom()).json()

    assert bom["lines"] == []
    assert bom["report"]["parts"] == []
    assert bom["report"]["summary"]["complete"] is True


@pytest.mark.parametrize("status", [s for s in RevisionStatus if s is not RevisionStatus.DRAFT])
def test_a_bom_that_isnt_a_drafts_cant_change(bench: Bench, status: RevisionStatus) -> None:
    bench.locked(status)

    bom = bench.client.get(bench.bom()).json()

    assert (bom["status"], bom["editable"]) == (status.value, False)


def test_the_bom_of_a_revision_that_doesnt_exist_is_not_found(bench: Bench) -> None:
    # Requirements 4.12 and 9.4: another workspace's revision reads the same way.
    response = bench.client.get(f"/api/projects/revisions/{MADE_UP}/bom")

    assert response.status_code == 404
    assert response.json()["detail"] == "that revision doesn't exist"


# --- Adding -----------------------------------------------------------------------------------


def test_a_line_is_added_as_typed_and_answered_canonically(bench: Bench) -> None:
    # The design's example on the wire: the designators read, counted and written back, the
    # notes collapsed.
    line = bench.add(
        {
            "part_id": str(bench.resistor),
            "designators": "r1-2, R7",
            "quantity": None,
            "notes": "  I²C   pull-ups ",
        }
    )

    assert line["designators"] == ["R1", "R2", "R7"]
    assert line["designator_text"] == "R1, R2, R7"
    assert (line["quantity"], line["notes"]) == (3, "I²C pull-ups")
    assert (line["revision_id"], line["part_id"]) == (str(bench.revision.id), str(bench.resistor))
    assert bench.world.work.commits == 1


@pytest.mark.parametrize("blank", ["", "   ", " ,\t, "])
def test_blank_designators_are_none_and_take_a_typed_quantity(bench: Bench, blank: str) -> None:
    line = bench.add({"part_id": str(bench.wire), "designators": blank, "quantity": 2})

    assert (line["designators"], line["designator_text"], line["quantity"]) == ([], "", 2)


def test_leaving_the_designators_out_is_none(bench: Bench) -> None:
    line = bench.add({"part_id": str(bench.wire), "quantity": 1})

    assert line["designators"] == []


@pytest.mark.parametrize("blank", ["", "   ", "\r\n\t"])
def test_blank_notes_read_as_none(bench: Bench, blank: str) -> None:
    line = bench.add({"part_id": str(bench.sensor), "designators": "U1", "notes": blank})

    assert line["notes"] is None


@pytest.mark.parametrize(
    ("body", "code", "field", "item"),
    [
        ({"designators": "U1A"}, "invalid_designator", "designators", "U1A"),
        ({"designators": "R4-R1"}, "invalid_range", "designators", "R4-R1"),
        ({"designators": "R1-R3, R2"}, "repeated_designator", "designators", "R2"),
        ({"designators": "R1-R257"}, "too_many_designators", "designators", None),
        ({"designators": "R1-4", "quantity": 5}, "quantity_mismatch", "quantity", None),
        ({"quantity": None}, "invalid_quantity", "quantity", None),
        ({"quantity": 10_001}, "invalid_quantity", "quantity", None),
        ({"quantity": 1, "notes": "x" * 501}, "invalid_notes", "notes", None),
    ],
)
def test_a_refused_value_answers_its_code_field_and_item(
    bench: Bench, body: dict[str, Any], code: str, field: str, item: str | None
) -> None:
    # Requirements 3.1 to 3.6, 4.3 to 4.5 and 11.7: a 422 the editor marks on its field.
    response = bench.client.post(bench.lines(), json={"part_id": str(bench.resistor), **body})

    assert response.status_code == 422
    detail = refusal(response)
    assert (detail["code"], detail["field"], detail["item"]) == (code, field, item)
    assert (detail["line_id"], detail["line"]) == (None, None)
    assert bench.world.work.commits == 0


def test_a_quantity_mismatch_says_how_many_designators_there_are(bench: Bench) -> None:
    response = bench.client.post(
        bench.lines(),
        json={"part_id": str(bench.resistor), "designators": "R1-R4", "quantity": 5},
    )

    assert refusal(response)["message"] == "R1–R4 are 4 designators, so the quantity is 4, not 5"


def test_a_part_the_catalog_doesnt_hold_is_refused_on_the_part(bench: Bench) -> None:
    # Requirements 4.2 and 9.3.
    response = bench.client.post(bench.lines(), json={"part_id": str(uuid7()), "designators": "R1"})

    assert response.status_code == 422
    detail = refusal(response)
    assert (detail["code"], detail["field"]) == ("unknown_part", "part")
    assert detail["message"] == "that part isn't in the catalog"


def test_a_designator_another_line_holds_is_a_conflict_naming_that_line(bench: Bench) -> None:
    # Requirement 4.6, as the design's example answers it.
    holder = bench.hold_line(bench.resistor, "R5-R7")

    response = bench.client.post(
        bench.lines(), json={"part_id": str(bench.sensor), "designators": "R7"}
    )

    assert response.status_code == 409
    assert refusal(response) == {
        "message": "R7 is already on the line R5–R7",
        "code": "designator_taken",
        "field": "designators",
        "item": "R7",
        "line_id": str(holder.id),
        "line": "R5–R7",
    }
    assert bench.world.work.commits == 0


def test_a_501st_line_is_refused_with_no_field(bench: Bench) -> None:
    # Requirement 4.7.
    for minutes in range(MAX_LINES):
        bench.hold_line(bench.wire, quantity=1, minutes=minutes)

    response = bench.client.post(bench.lines(), json={"part_id": str(bench.wire), "quantity": 1})

    assert response.status_code == 422
    detail = refusal(response)
    assert (detail["code"], detail["field"]) == ("too_many_lines", None)


def test_a_line_on_a_revision_that_isnt_a_draft_is_a_conflict(bench: Bench) -> None:
    # Requirement 5.1: the request was fine, the revision's state refuses it.
    bench.locked(RevisionStatus.BUILT)

    response = bench.client.post(
        bench.lines(), json={"part_id": str(bench.sensor), "designators": "U1"}
    )

    assert response.status_code == 409
    detail = refusal(response)
    assert (detail["code"], detail["field"], detail["item"]) == ("revision_locked", None, None)
    assert bench.world.work.commits == 0


def test_a_line_on_a_revision_that_doesnt_exist_is_not_found(bench: Bench) -> None:
    response = bench.client.post(
        f"/api/projects/revisions/{MADE_UP}/bom/lines",
        json={"part_id": str(bench.sensor), "designators": "U1"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "that revision doesn't exist"


@pytest.mark.parametrize("field", ["designators", "notes"])
def test_typed_text_is_taken_up_to_4000_characters(bench: Bench, field: str) -> None:
    # The transport bound (design's Limits): the domain decides what 4,000 characters mean,
    # and past them the request schema refuses the body with FastAPI's own list.
    padded = {"designators": "R1" + " " * 3_998, "notes": "x" + " " * 3_999}[field]
    body = {"part_id": str(bench.resistor), "designators": "R1", field: padded}

    at_the_bound = bench.client.post(bench.lines(), json=body)
    past_it = bench.client.post(bench.lines(), json={**body, field: padded + " "})

    assert at_the_bound.status_code == 201, at_the_bound.text
    assert past_it.status_code == 422
    assert isinstance(past_it.json()["detail"], list)


def test_a_part_id_that_isnt_a_uuid_is_refused_by_the_schema(bench: Bench) -> None:
    response = bench.client.post(bench.lines(), json={"part_id": "R1", "designators": "R1"})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


# --- Editing ----------------------------------------------------------------------------------


def test_a_line_is_edited_whole(bench: Bench) -> None:
    # Requirement 4.9: its own designators don't count against it.
    line = bench.hold_line(bench.resistor, "R1-3")

    response = bench.client.patch(
        f"{bench.lines()}/{line.id}",
        json={"part_id": str(bench.resistor), "designators": "R2-R4", "notes": "pull-ups"},
    )

    assert response.status_code == 200
    edited = response.json()
    assert (edited["id"], edited["designator_text"], edited["quantity"]) == (
        str(line.id),
        "R2–R4",
        3,
    )
    assert edited["notes"] == "pull-ups"
    assert bench.world.work.commits == 1


def test_an_edit_that_changes_nothing_writes_nothing(bench: Bench) -> None:
    line = bench.hold_line(bench.resistor, "R1-3")

    response = bench.client.patch(
        f"{bench.lines()}/{line.id}",
        json={"part_id": str(bench.resistor), "designators": "r1, r2, r3", "notes": " "},
    )

    assert response.status_code == 200
    assert response.json()["designator_text"] == "R1–R3"
    assert bench.world.work.commits == 0


def test_an_edit_onto_a_designator_another_line_holds_is_a_conflict(bench: Bench) -> None:
    holder = bench.hold_line(bench.resistor, "R1-R4")
    line = bench.hold_line(bench.sensor, "U1", minutes=1)

    response = bench.client.patch(
        f"{bench.lines()}/{line.id}", json={"part_id": str(bench.sensor), "designators": "R4"}
    )

    assert response.status_code == 409
    assert (refusal(response)["line_id"], refusal(response)["line"]) == (str(holder.id), "R1–R4")


def test_an_edit_refused_on_its_value_answers_the_field(bench: Bench) -> None:
    line = bench.hold_line(bench.wire, quantity=1)

    response = bench.client.patch(
        f"{bench.lines()}/{line.id}", json={"part_id": str(bench.wire), "quantity": 0}
    )

    assert response.status_code == 422
    assert refusal(response)["field"] == "quantity"


def test_a_line_named_under_another_revision_is_not_found(bench: Bench) -> None:
    # Requirement 4.12: a line id is only ever found under its own revision.
    line = bench.hold_line(bench.sensor, "U1")
    other = bench.world.hold_revision(bench.project, "B")

    edited = bench.client.patch(
        f"{bench.lines(other)}/{line.id}", json={"part_id": str(bench.sensor), "designators": "U2"}
    )
    removed = bench.client.delete(f"{bench.lines(other)}/{line.id}")

    assert (edited.status_code, removed.status_code) == (404, 404)
    assert edited.json()["detail"] == "that line isn't on this revision's BOM"
    assert line.id in bench.world.work.bom_lines.saved


def test_a_line_that_doesnt_exist_is_not_found(bench: Bench) -> None:
    response = bench.client.patch(
        f"{bench.lines()}/{MADE_UP}", json={"part_id": str(bench.sensor), "designators": "U1"}
    )

    assert response.status_code == 404


def test_an_edit_on_a_revision_that_isnt_a_draft_is_a_conflict(bench: Bench) -> None:
    line = bench.hold_line(bench.sensor, "U1")
    bench.locked()

    response = bench.client.patch(
        f"{bench.lines()}/{line.id}", json={"part_id": str(bench.sensor), "designators": "U2"}
    )

    assert response.status_code == 409
    assert refusal(response)["code"] == "revision_locked"


# --- Removing ---------------------------------------------------------------------------------


def test_a_line_is_removed(bench: Bench) -> None:
    # Requirement 4.10.
    line = bench.hold_line(bench.sensor, "U1")

    response = bench.client.delete(f"{bench.lines()}/{line.id}")

    assert response.status_code == 204
    assert bench.world.work.bom_lines.saved == {}
    assert bench.world.work.commits == 1


def test_removing_a_line_that_doesnt_exist_is_not_found(bench: Bench) -> None:
    assert bench.client.delete(f"{bench.lines()}/{MADE_UP}").status_code == 404


def test_removing_from_a_revision_that_isnt_a_draft_is_a_conflict(bench: Bench) -> None:
    line = bench.hold_line(bench.sensor, "U1")
    bench.locked(RevisionStatus.DISMANTLED)

    response = bench.client.delete(f"{bench.lines()}/{line.id}")

    assert response.status_code == 409
    assert refusal(response)["code"] == "revision_locked"
    assert line.id in bench.world.work.bom_lines.saved


# --- The wire contract ------------------------------------------------------------------------


def test_the_wire_names_match_their_enums() -> None:
    # A new status, field or code stops type-checking in the schemas; this catches a name
    # listed here that the enum doesn't have.
    assert set(get_args(StockStatusName.__value__)) == {s.value for s in StockStatus}
    assert set(get_args(BomFieldName.__value__)) == {f.value for f in BomField}
    assert set(get_args(BomRefusalCodeName.__value__)) == {c.value for c in ContentRefusal}
