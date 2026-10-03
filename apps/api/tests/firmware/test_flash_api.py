"""The flash log's routes over the in-memory fakes: a bare FastAPI, no database (15-flash-log,
HTTP).

The router's own contract: each route's status, each refusal of the design's Error Handling
with its status, code, field and item, a refused delete's flashes, and the shapes on the wire
the web builds on. The workspace dependency is a stub, as in `test_firmware_api.py`; the
session and CSRF checks are `test_firmware_auth.py`'s.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import Response

from support.firmware import BENCH, NOW, World
from wiredex.firmware.api.router import create_router
from wiredex.firmware.application.ports import RevisionFacts
from wiredex.firmware.domain.errors import FirmwareField, FirmwareRefusal
from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.flash import Flash
from wiredex.firmware.domain.values import Framework, UnitId, WorkspaceId

FIRMWARE = "/api/firmware"
VERSIONS = f"{FIRMWARE}/versions"
UNITS = f"{FIRMWARE}/units"
FLASHES = f"{FIRMWARE}/flashes"
MADE_UP = "0199aaaa-0000-7000-8000-000000000000"
# The fakes' clock, NOW, as the API writes it.
STAMP = "2026-09-30T03:00:00Z"
JSON_BODY = {"content-type": "application/json"}


async def the_bench(_request: Request) -> WorkspaceId:
    """What `bootstrap/app.py` builds from the session: the workspace this request acts in."""
    return BENCH


def mounted(world: World) -> FastAPI:
    app = FastAPI()
    app.include_router(create_router(world.firmware_use_cases(), the_bench), prefix="/api")
    return app


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def client(world: World) -> TestClient:
    return TestClient(mounted(world))


def answered(response: Response, status: int = 200) -> Any:
    """The body of a request expected to work, so a test can get on with its point."""
    assert response.status_code == status, response.text
    return response.json()


def refusal(response: Response, status: int) -> dict[str, Any]:
    """The `detail` of a refused write: its message, code, field, item and flashes."""
    assert response.status_code == status, response.text
    detail: dict[str, Any] = response.json()["detail"]
    return detail


def flashes_of(unit_id: UnitId | str) -> str:
    return f"{UNITS}/{unit_id}/flashes"


def pico_blink(world: World) -> Firmware:
    return world.hold_firmware("Pico blink", target="RPI_PICO", framework=Framework.MICROPYTHON)


def stamp(moment: datetime) -> str:
    """A time as the API writes it, in UTC with a `Z`."""
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def runs_on(revision: RevisionFacts) -> dict[str, Any]:
    return {
        "revision_id": str(revision.revision_id),
        "project_id": str(revision.project_id),
        "project_name": revision.project_name,
        "label": revision.label,
        "summary": revision.summary,
    }


def entry(
    flash: Flash, firmware: Firmware, number: str, revision: RevisionFacts | None = None
) -> dict[str, Any]:
    """A flash as a log answers it, with the revision it recorded while the bench holds it."""
    return {
        "id": str(flash.id),
        "unit": {"id": str(flash.unit_id), "code": str(flash.unit_code)},
        "firmware_id": str(firmware.id),
        "firmware_name": str(firmware.name),
        "version": {"id": str(flash.version_id), "version": number},
        "revision": None if revision is None else runs_on(revision),
        "flashed_at": stamp(flash.flashed_at),
        "notes": None if flash.notes is None else str(flash.notes),
        "created_at": stamp(flash.created_at),
    }


# --- Logging a flash ------------------------------------------------------------------------


def test_a_flash_answers_its_entry_with_its_time_in_utc(client: TestClient, world: World) -> None:
    # Requirements 1.1, 1.3, 1.7 to 1.9: the time sent with the browser's offset is the same
    # instant in UTC, stored and answered so, as every later read from PostgreSQL answers it;
    # the notes collapsed; the revision holding the unit recorded and named.
    firmware = pico_blink(world)
    release = world.hold_version(firmware, "1.0.0", released=True)
    revision = world.directory.hold("Greenhouse controller", "A", "breadboard")
    pico = world.units.hold(revision_id=revision.revision_id)

    body = answered(
        client.post(
            flashes_of(pico.unit_id),
            json={
                "version_id": str(release.id),
                "flashed_at": "2026-09-29T21:30:00-03:00",
                "notes": "  Bench test   before the build ",
            },
        ),
        201,
    )

    [flash] = world.work.flashes.saved.values()
    assert body == {
        "id": str(flash.id),
        "unit": {"id": str(pico.unit_id), "code": "WX-U-0001"},
        "firmware_id": str(firmware.id),
        "firmware_name": "Pico blink",
        "version": {"id": str(release.id), "version": "1.0.0"},
        "revision": runs_on(revision),
        "flashed_at": "2026-09-30T00:30:00Z",
        "notes": "Bench test before the build",
        "created_at": STAMP,
    }
    assert flash.flashed_at == datetime(2026, 9, 30, 0, 30, tzinfo=UTC)
    assert flash.flashed_at.tzinfo is UTC
    assert world.work.commits == 1


@pytest.mark.parametrize("notes", [None, "", " \t "])
def test_a_flash_with_no_time_is_flashed_now_and_blank_notes_are_none(
    client: TestClient, world: World, notes: str | None
) -> None:
    # Requirements 1.2 and 1.9.
    release = world.hold_version(pico_blink(world), "1.0.0", released=True)
    pico = world.units.hold()

    body = answered(
        client.post(flashes_of(pico.unit_id), json={"version_id": str(release.id), "notes": notes}),
        201,
    )

    assert (body["flashed_at"], body["notes"], body["revision"]) == (STAMP, None, None)


def test_a_time_without_an_offset_is_refused_by_the_schema(
    client: TestClient, world: World
) -> None:
    # Design's HTTP section: the browser's clock and the server's would read it apart.
    release = world.hold_version(pico_blink(world), "1.0.0", released=True)
    pico = world.units.hold()

    response = client.post(
        flashes_of(pico.unit_id),
        json={"version_id": str(release.id), "flashed_at": "2026-09-30T00:30:00"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "flashed_at"]
    assert world.work.commits == 0


def test_a_draft_or_a_retired_unit_is_a_409_naming_it(client: TestClient, world: World) -> None:
    # Requirements 1.5 and 1.6: nothing written either way.
    firmware = pico_blink(world)
    draft = world.hold_version(firmware, "1.1.0")
    release = world.hold_version(firmware, "1.0.0", released=True)
    pico = world.units.hold()
    lost = world.units.hold(retired=True)

    drafted = client.post(flashes_of(pico.unit_id), json={"version_id": str(draft.id)})
    retired = client.post(flashes_of(lost.unit_id), json={"version_id": str(release.id)})

    assert refusal(drafted, 409) == {
        "message": (
            "1.1.0 is a draft and can still change: release it before logging a flash of it"
        ),
        "code": "not_released",
        "field": "version",
        "item": "1.1.0",
        "flashes": [],
    }
    detail = refusal(retired, 409)
    assert (detail["code"], detail["field"], detail["item"]) == (
        "unit_retired",
        "unit",
        "WX-U-0002",
    )
    assert world.work.flashes.saved == {}
    assert world.work.commits == 0


@pytest.mark.parametrize(
    ("change", "code", "field"),
    [
        ({"flashed_at": "2026-09-30T03:05:01Z"}, "flashed_in_future", "flashed_at"),
        ({"notes": "x" * 501}, "invalid_notes", "notes"),
        ({"notes": "bench\x07test"}, "invalid_notes", "notes"),
    ],
)
def test_a_time_too_far_ahead_or_notes_the_log_wont_take_are_refused_on_their_field(
    client: TestClient, world: World, change: dict[str, str], code: str, field: str
) -> None:
    # Requirements 1.4 and 1.9: five minutes ahead and one second more; 500 characters and one
    # more; a control character.
    release = world.hold_version(pico_blink(world), "1.0.0", released=True)
    pico = world.units.hold()

    response = client.post(flashes_of(pico.unit_id), json={"version_id": str(release.id), **change})

    detail = refusal(response, 422)
    assert (detail["code"], detail["field"], detail["item"]) == (code, field, None)
    assert world.work.commits == 0


def test_half_a_surrogate_pair_in_the_notes_is_refused_in_an_answer_that_encodes(
    client: TestClient, world: World
) -> None:
    # Requirement 1.9: no bound in the request schema refuses the escape first, which would
    # answer a 500 for an input UTF-8 can't encode; `FlashNotes` refuses it on the notes.
    release = world.hold_version(pico_blink(world), "1.0.0", released=True)
    pico = world.units.hold()
    body = json.dumps({"version_id": str(release.id), "notes": "bench \ud800"}).encode("ascii")

    response = client.post(flashes_of(pico.unit_id), content=body, headers=JSON_BODY)

    assert refusal(response, 422)["code"] == "invalid_notes"
    assert world.work.commits == 0


def test_a_flash_on_a_unit_or_of_a_version_the_workspace_doesnt_hold_is_a_404(
    client: TestClient, world: World
) -> None:
    # Requirements 1.10 and 6.2: the fakes hold one bench, so another bench's ids are among the
    # made-up ones; either missing writes nothing.
    release = world.hold_version(pico_blink(world), "1.0.0", released=True)
    pico = world.units.hold()

    no_unit = client.post(flashes_of(MADE_UP), json={"version_id": str(release.id)})
    no_version = client.post(flashes_of(pico.unit_id), json={"version_id": MADE_UP})

    assert (no_unit.status_code, no_unit.json()) == (404, {"detail": "that unit doesn't exist"})
    assert (no_version.status_code, no_version.json()) == (
        404,
        {"detail": "that version doesn't exist"},
    )
    assert world.work.flashes.saved == {}
    assert world.work.commits == 0


@pytest.mark.parametrize(
    "path", [f"{UNITS}/{MADE_UP}", f"{FIRMWARE}/{MADE_UP}/boards", f"{FLASHES}/{MADE_UP}"]
)
def test_a_unit_firmware_or_flash_the_workspace_doesnt_hold_is_a_404(
    client: TestClient, world: World, path: str
) -> None:
    # Requirements 2.5, 3.3, 4.3 and 6.2: read, or removed for the flash.
    method = "DELETE" if path.startswith(FLASHES) else "GET"

    response = client.request(method, path)

    assert response.status_code == 404
    assert world.work.commits == 0


# --- Reading a board's log, and removing an entry -------------------------------------------


def test_a_units_log_answers_its_current_version_and_the_newer_release(
    client: TestClient, world: World
) -> None:
    # Requirements 2.1 to 2.3: newest first by when each was flashed, a downgrade current;
    # each with the revision it recorded while the bench still holds it; the firmware's latest
    # release above the current version.
    firmware = pico_blink(world)
    first = world.hold_version(firmware, "1.0.0", released=True)
    latest = world.hold_version(firmware, "1.1.0", released=True)
    gone = world.directory.hold("Weather station", "A")
    greenhouse = world.directory.hold("Greenhouse controller", "A")
    pico = world.units.hold(revision_id=greenhouse.revision_id)
    earlier = world.hold_flash(
        replace(pico, revision_id=gone.revision_id), latest, flashed_at=NOW - timedelta(days=3)
    )
    current = world.hold_flash(
        pico, first, flashed_at=NOW - timedelta(days=1), notes="Back to 1.0.0"
    )
    del world.directory.held[gone.revision_id]

    body = answered(client.get(f"{UNITS}/{pico.unit_id}"))

    assert body == {
        "unit": {"id": str(pico.unit_id), "code": "WX-U-0001"},
        "retired": False,
        "current": entry(current, firmware, "1.0.0", greenhouse),
        "newer_release": {"id": str(latest.id), "version": "1.1.0"},
        "flashes": [
            entry(current, firmware, "1.0.0", greenhouse),
            entry(earlier, firmware, "1.1.0"),
        ],
    }


def test_a_retired_units_log_says_so_and_an_empty_one_has_no_current_version(
    client: TestClient, world: World
) -> None:
    # Requirements 2.2 and 2.4.
    lost = world.units.hold(retired=True)

    body = answered(client.get(f"{UNITS}/{lost.unit_id}"))

    assert body == {
        "unit": {"id": str(lost.unit_id), "code": "WX-U-0001"},
        "retired": True,
        "current": None,
        "newer_release": None,
        "flashes": [],
    }


def test_removing_the_newest_flash_makes_the_one_before_it_current(
    client: TestClient, world: World
) -> None:
    # Requirements 3.1 to 3.3: once removed, the flash is a 404 like any other.
    firmware = pico_blink(world)
    first = world.hold_version(firmware, "1.0.0", released=True)
    latest = world.hold_version(firmware, "1.1.0", released=True)
    pico = world.units.hold()
    world.hold_flash(pico, first, flashed_at=NOW - timedelta(days=2))
    newest = world.hold_flash(pico, latest, flashed_at=NOW - timedelta(days=1))

    removed = client.delete(f"{FLASHES}/{newest.id}")
    again = client.delete(f"{FLASHES}/{newest.id}")
    body = answered(client.get(f"{UNITS}/{pico.unit_id}"))

    assert (removed.status_code, again.status_code) == (204, 404)
    assert body["current"]["version"] == {"id": str(first.id), "version": "1.0.0"}
    assert body["newer_release"] == {"id": str(latest.id), "version": "1.1.0"}
    assert world.work.commits == 1


# --- A firmware's boards --------------------------------------------------------------------


def test_a_firmwares_boards_by_code_with_where_each_is_now(
    client: TestClient, world: World
) -> None:
    # Requirements 4.1 and 4.2: a retired unit left out; the revision holding the unit now
    # beside the one its flash recorded; the newer release for a board on an older version.
    firmware = pico_blink(world)
    old = world.hold_version(firmware, "1.0.0", released=True)
    new = world.hold_version(firmware, "1.1.0", released=True)
    greenhouse = world.directory.hold("Greenhouse controller", "A")
    held = world.units.hold("WX-U-0007", revision_id=greenhouse.revision_id)
    loose = world.units.hold("WX-U-0003")
    lost = world.units.hold("WX-U-0001", retired=True)
    flashed = world.hold_flash(held, new, flashed_at=NOW - timedelta(days=1))
    world.hold_flash(loose, old, flashed_at=NOW - timedelta(days=2))
    world.hold_flash(lost, new)

    boards = answered(client.get(f"{FIRMWARE}/{firmware.id}/boards"))

    assert [
        (board["unit"]["code"], board["flash"]["version"]["version"], board["newer_release"])
        for board in boards
    ] == [
        ("WX-U-0003", "1.0.0", {"id": str(new.id), "version": "1.1.0"}),
        ("WX-U-0007", "1.1.0", None),
    ]
    assert boards[1] == {
        "unit": {"id": str(held.unit_id), "code": "WX-U-0007"},
        "revision": runs_on(greenhouse),
        "flash": entry(flashed, firmware, "1.1.0", greenhouse),
        "newer_release": None,
    }
    assert boards[0]["revision"] is None


# --- Keeping the record ---------------------------------------------------------------------


def test_a_flashed_version_refuses_its_delete_listing_the_flashes_to_remove(
    client: TestClient, world: World
) -> None:
    # Requirements 3.1, 5.1 and 5.3: each flash with its unit's code and whether inventory still
    # holds the unit; a deleted unit's entry removed from there too, and then the version goes.
    firmware = pico_blink(world)
    release = world.hold_version(firmware, "1.0.0", released=True)
    pico = world.units.hold()
    deleted = world.units.hold()
    kept = world.hold_flash(pico, release, flashed_at=NOW - timedelta(days=2))
    orphan = world.hold_flash(deleted, release, flashed_at=NOW - timedelta(days=1))
    del world.units.held[deleted.unit_id]
    before = world.snapshot()

    detail = refusal(client.delete(f"{VERSIONS}/{release.id}"), 409)
    unchanged = world.snapshot() == before
    removed = [client.delete(f"{FLASHES}/{one['id']}").status_code for one in detail["flashes"]]
    deleted_now = client.delete(f"{VERSIONS}/{release.id}")

    tag = {"id": str(release.id), "version": "1.0.0"}
    assert detail == {
        "message": "1.0.0 is in the flash logs of 2 boards; remove those entries to delete it",
        "code": "version_flashed",
        "field": None,
        "item": "1.0.0",
        "flashes": [
            {
                "id": str(kept.id),
                "unit": {"id": str(pico.unit_id), "code": "WX-U-0001"},
                "unit_present": True,
                "version": tag,
                "flashed_at": "2026-09-28T03:00:00Z",
            },
            {
                "id": str(orphan.id),
                "unit": {"id": str(deleted.unit_id), "code": "WX-U-0002"},
                "unit_present": False,
                "version": tag,
                "flashed_at": "2026-09-29T03:00:00Z",
            },
        ],
    }
    assert unchanged
    assert (removed, deleted_now.status_code) == ([204, 204], 204)
    assert world.work.versions.saved == {}


def test_a_firmware_a_board_runs_refuses_its_delete_listing_the_flashes(
    client: TestClient, world: World
) -> None:
    # Requirement 5.2: a flash of any of its versions keeps the firmware, and nothing goes.
    firmware = pico_blink(world)
    first = world.hold_version(firmware, "1.0.0", released=True)
    latest = world.hold_version(firmware, "1.1.0", released=True)
    one, other = world.units.hold(), world.units.hold()
    world.hold_flash(one, first)
    world.hold_flash(other, latest)
    before = world.snapshot()

    detail = refusal(client.delete(f"{FIRMWARE}/{firmware.id}"), 409)

    assert (detail["code"], detail["field"], detail["item"]) == (
        "firmware_flashed",
        None,
        "Pico blink",
    )
    assert detail["message"] == (
        "Pico blink is in the flash logs of 2 boards; remove those entries to move it to the trash"
    )
    assert [
        (flash["unit"]["code"], flash["version"]["version"]) for flash in detail["flashes"]
    ] == [
        ("WX-U-0001", "1.0.0"),
        ("WX-U-0002", "1.1.0"),
    ]
    assert world.snapshot() == before
    assert world.work.commits == 0


# --- The wire -------------------------------------------------------------------------------


def test_the_flash_refusals_reach_the_schema_the_client_is_generated_from(world: World) -> None:
    # Requirement 9.4 and decision 13: the widened unions are what OpenAPI lists, a refusal
    # always carries its flashes, and the two deletes declare their structured 409, so the
    # generated client types every one of them.
    schema = mounted(world).openapi()
    components = schema["components"]["schemas"]
    refused = {"$ref": "#/components/schemas/FirmwareRefusalResponse"}

    assert set(components["FirmwareRefusalCodeName"]["enum"]) == {
        code.value for code in FirmwareRefusal
    }
    assert set(components["FirmwareFieldName"]["enum"]) == {field.value for field in FirmwareField}
    assert "flashes" in components["FirmwareRefusalResponse"]["required"]
    for path in (f"{VERSIONS}/{{version_id}}", f"{FIRMWARE}/{{firmware_id}}"):
        conflict = schema["paths"][path]["delete"]["responses"]["409"]
        assert conflict["content"]["application/json"]["schema"] == refused
