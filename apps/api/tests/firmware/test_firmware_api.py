"""The firmware routes over the in-memory fakes: a bare FastAPI, no database.

The router's own contract (13-firmware-versions, HTTP): every route's status, each refusal of
the design's Error Handling with its status, code, field and item, and the shapes on the wire the
web builds on. The workspace dependency is a stub, because resolving it is identity's job and the
composition root's wiring, which `test_firmware_auth.py` covers.
"""

import json
from datetime import timedelta
from typing import Any, get_args
from uuid import uuid7

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import Response

from support.firmware import BENCH, World
from wiredex.firmware.api.router import create_router
from wiredex.firmware.api.schemas import (
    FirmwareFieldName,
    FirmwareRefusalCodeName,
    FrameworkName,
    VersionStatusName,
)
from wiredex.firmware.domain.errors import FirmwareField, FirmwareRefusal
from wiredex.firmware.domain.source import MAX_FILES, MAX_VERSION_BYTES
from wiredex.firmware.domain.values import Description, Framework, RevisionId, WorkspaceId
from wiredex.firmware.domain.version import FirmwareVersion, VersionStatus

FIRMWARE = "/api/firmware"
VERSIONS = f"{FIRMWARE}/versions"
MADE_UP = "0199aaaa-0000-7000-8000-000000000000"
# The fakes' clock, NOW, as the API writes it.
STAMP = "2026-09-30T03:00:00Z"
ESP32 = {"name": "Weather station", "target": "esp32:esp32:esp32", "framework": "arduino"}
JSON_BODY = {"content-type": "application/json"}


async def the_bench(_request: Request) -> WorkspaceId:
    """What `bootstrap/app.py` builds from the session: the workspace this request acts in."""
    return BENCH


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def client(world: World) -> TestClient:
    app = FastAPI()
    app.include_router(create_router(world.firmware_use_cases(), the_bench), prefix="/api")
    return TestClient(app)


def answered(response: Response, status: int = 200) -> Any:
    """The body of a request expected to work, so a test can get on with its point."""
    assert response.status_code == status, response.text
    return response.json()


def refusal(response: Response, status: int) -> dict[str, Any]:
    """The `detail` of a refused write: its message, code, field and item (decision 13)."""
    assert response.status_code == status, response.text
    detail: dict[str, Any] = response.json()["detail"]
    return detail


def files_of(version: FirmwareVersion) -> str:
    return f"{VERSIONS}/{version.id}/files"


def escaped_json(body: object) -> bytes:
    """The body as JSON with every character past ASCII escaped, the way a browser's
    `JSON.stringify` sends half of a surrogate pair: `\\ud800`. `json=` writes UTF-8, which
    can't hold one."""
    return json.dumps(body).encode("ascii")


# --- Firmware -------------------------------------------------------------------------------


def test_a_new_firmware_answers_its_page_with_no_versions(client: TestClient) -> None:
    # Requirements 1.1, 1.2, 1.4, 1.6 and 1.8: the details as stored, and 0.1.0 to start with.
    body = answered(
        client.post(
            FIRMWARE,
            json={
                "name": "  Weather   station ",
                "target": " esp32:esp32:esp32 ",
                "framework": "arduino",
                "description": "Reads a BME280\r\nevery five minutes.  ",
            },
        ),
        201,
    )

    assert body == {
        "id": body["id"],
        "name": "Weather station",
        "target": "esp32:esp32:esp32",
        "framework": "arduino",
        "description": "Reads a BME280\nevery five minutes.",
        "created_at": STAMP,
        "updated_at": STAMP,
        "runs_on": [],
        "versions": [],
        "latest_release": None,
        "suggested_version": "0.1.0",
    }


def test_a_firmware_created_for_a_revision_runs_on_it(client: TestClient, world: World) -> None:
    # Requirements 3.3 and 3.5: the revision named by its project, label and summary.
    revision = world.directory.hold("Weather station", "A", "breadboard")

    body = answered(
        client.post(FIRMWARE, json={**ESP32, "revision_id": str(revision.revision_id)}), 201
    )

    assert body["runs_on"] == [
        {
            "revision_id": str(revision.revision_id),
            "project_id": str(revision.project_id),
            "project_name": "Weather station",
            "label": "A",
            "summary": "breadboard",
        }
    ]


def test_a_firmware_for_a_revision_the_workspace_doesnt_hold_is_a_404(
    client: TestClient, world: World
) -> None:
    # Requirements 3.7 and 9.2: another bench's revision is simply not found.
    response = client.post(FIRMWARE, json={**ESP32, "revision_id": MADE_UP})

    assert (response.status_code, response.json()) == (
        404,
        {"detail": "that revision doesn't exist"},
    )
    assert world.work.commits == 0


@pytest.mark.parametrize("blank", ["", "   ", "\r\n\t"])
def test_a_blank_description_reads_as_none(client: TestClient, blank: str) -> None:
    body = answered(client.post(FIRMWARE, json={**ESP32, "description": blank}), 201)

    assert body["description"] is None


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("name", " \t ", "invalid_name"),
        ("name", "x" * 121, "invalid_name"),
        ("target", "esp32\x07", "invalid_target"),
        ("description", "x" * 4_001, "invalid_description"),
    ],
)
def test_details_their_values_refuse_are_unprocessable_on_their_field(
    client: TestClient, world: World, field: str, value: str, code: str
) -> None:
    # Requirements 1.2, 1.4 and 1.6, marked on the field the form shows them by.
    detail = refusal(client.post(FIRMWARE, json={**ESP32, field: value}), 422)

    assert (detail["code"], detail["field"], detail["item"]) == (code, field, None)
    assert world.work.commits == 0


def test_an_unknown_framework_is_refused_by_the_schema(client: TestClient) -> None:
    # Requirement 1.5: the five frameworks are the request's own union.
    response = client.post(FIRMWARE, json={**ESP32, "framework": "zephyr"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "framework"]


def test_a_name_another_firmware_holds_is_a_409_naming_it(client: TestClient, world: World) -> None:
    # Requirement 1.3: ignoring case; the item is the name as the request normalized it.
    world.hold_firmware("Weather station")

    detail = refusal(client.post(FIRMWARE, json={**ESP32, "name": "WEATHER  station"}), 409)

    assert detail == {
        "message": "there is already a firmware named Weather station",
        "code": "name_taken",
        "field": "name",
        "item": "WEATHER station",
        "flashes": [],
    }
    assert world.work.commits == 0


def test_the_list_opens_on_the_last_change_and_narrows_by_name_or_target(
    client: TestClient, world: World
) -> None:
    # Requirements 2.1 to 2.4: `%` matches only itself, and nothing matching is an empty list.
    weather = world.hold_firmware("Weather station", minutes=2)
    released = world.hold_version(weather, "1.0.0", released=True)
    world.hold_version(weather, "1.1.0")
    world.hold_firmware("Pico blink", target="RPI_PICO", framework=Framework.MICROPYTHON, minutes=1)
    world.hold_firmware("Greenhouse controller", minutes=3)

    everything = answered(client.get(FIRMWARE))
    esp32 = answered(client.get(FIRMWARE, params={"search": "ESP32"}))
    nothing = answered(client.get(FIRMWARE, params={"search": "100%"}))

    assert [one["name"] for one in everything] == [
        "Greenhouse controller",
        "Weather station",
        "Pico blink",
    ]
    assert [one["name"] for one in esp32] == ["Greenhouse controller", "Weather station"]
    assert esp32[1] == {
        "id": str(weather.id),
        "name": "Weather station",
        "target": "esp32:esp32:esp32",
        "framework": "arduino",
        "latest_release": {"id": str(released.id), "version": "1.0.0"},
        "versions": 2,
        "drafts": 1,
        "updated_at": "2026-09-30T03:02:00Z",
    }
    assert nothing == []


def test_a_revisions_firmware_by_name(client: TestClient, world: World) -> None:
    # Requirements 3.4 and 3.7: every firmware linked to it and no other, and a 404 for a
    # revision the workspace doesn't hold.
    revision = world.directory.hold()
    for name in ("Weather station", "Blink"):
        world.hold_link(world.hold_firmware(name), revision.revision_id)
    world.hold_firmware("Greenhouse controller")

    listed = answered(client.get(f"{FIRMWARE}/revisions/{revision.revision_id}"))
    unknown = client.get(f"{FIRMWARE}/revisions/{MADE_UP}")

    assert [(one["name"], one["latest_release"]) for one in listed] == [
        ("Blink", None),
        ("Weather station", None),
    ]
    assert unknown.status_code == 404


def test_a_firmware_opens_with_its_versions_highest_first(client: TestClient, world: World) -> None:
    # Requirements 1.8, 3.5 and 3.6: the revisions in link order, one the workspace lost left
    # out; each version with its base, file count and bytes; the successor of the highest.
    firmware = world.hold_firmware("Weather station")
    first = world.hold_version(firmware, "1.0.0", released=True)
    world.hold_file(first, "weather_station.ino", "void setup() {}\n")
    second = world.hold_version(firmware, "1.1.0-rc.1", based_on=first)
    breadboard = world.directory.hold("Weather station", "A")
    perfboard = world.directory.hold("Weather station", "B")
    world.hold_link(firmware, perfboard.revision_id)
    world.hold_link(firmware, RevisionId(uuid7()), minutes=1)
    world.hold_link(firmware, breadboard.revision_id, minutes=2)

    body = answered(client.get(f"{FIRMWARE}/{firmware.id}"))

    assert [revision["label"] for revision in body["runs_on"]] == ["B", "A"]
    assert body["versions"] == [
        {
            "id": str(second.id),
            "version": "1.1.0-rc.1",
            "status": "draft",
            "based_on": str(first.id),
            "released_at": None,
            "created_at": STAMP,
            "updated_at": STAMP,
            "files": 0,
            "size": 0,
        },
        {
            "id": str(first.id),
            "version": "1.0.0",
            "status": "released",
            "based_on": None,
            "released_at": STAMP,
            "created_at": STAMP,
            "updated_at": STAMP,
            "files": 1,
            "size": 16,
        },
    ]
    assert body["latest_release"] == {"id": str(first.id), "version": "1.0.0"}
    assert body["suggested_version"] == "1.1.0-rc.2"


def test_an_edit_replaces_the_details_whole(client: TestClient, world: World) -> None:
    # Requirement 1.7: the description the edit leaves out is gone.
    firmware = world.hold_firmware("Weather station")
    firmware.description = Description("Reads a BME280.")
    world.clock.advance(timedelta(minutes=5))

    body = answered(
        client.patch(
            f"{FIRMWARE}/{firmware.id}",
            json={
                "name": "Weather station S3",
                "target": "esp32:esp32:esp32s3",
                "framework": "platformio",
            },
        )
    )

    assert (body["name"], body["target"], body["framework"], body["description"]) == (
        "Weather station S3",
        "esp32:esp32:esp32s3",
        "platformio",
        None,
    )
    assert body["updated_at"] == "2026-09-30T03:05:00Z"
    assert world.work.commits == 1


def test_a_delete_takes_everything_the_firmware_holds(client: TestClient, world: World) -> None:
    # Requirements 1.9 and 1.10: once it is gone, it is a 404 like any other.
    firmware = world.hold_firmware("Weather station")
    world.hold_file(world.hold_version(firmware, "1.0.0"), "sketch.ino")

    deleted = client.delete(f"{FIRMWARE}/{firmware.id}")
    again = client.delete(f"{FIRMWARE}/{firmware.id}")

    assert (deleted.status_code, again.status_code) == (204, 404)
    assert client.get(f"{FIRMWARE}/{firmware.id}").status_code == 404
    assert (world.work.versions.saved, world.work.sources.saved) == ({}, {})


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", f"{FIRMWARE}/{MADE_UP}", None),
        ("PATCH", f"{FIRMWARE}/{MADE_UP}", ESP32),
        ("DELETE", f"{FIRMWARE}/{MADE_UP}", None),
        ("PUT", f"{FIRMWARE}/{MADE_UP}/revisions/{MADE_UP}", None),
        ("DELETE", f"{FIRMWARE}/{MADE_UP}/revisions/{MADE_UP}", None),
        ("POST", f"{FIRMWARE}/{MADE_UP}/versions", {}),
        ("GET", f"{VERSIONS}/{MADE_UP}", None),
        ("PATCH", f"{VERSIONS}/{MADE_UP}", {"version": "1.0.0"}),
        ("POST", f"{VERSIONS}/{MADE_UP}/release", None),
        ("DELETE", f"{VERSIONS}/{MADE_UP}", None),
        ("POST", f"{VERSIONS}/{MADE_UP}/files", {"files": [{"path": "a.ino", "content": ""}]}),
        ("PATCH", f"{VERSIONS}/{MADE_UP}/files/{MADE_UP}", {"path": "a.ino", "content": ""}),
        ("DELETE", f"{VERSIONS}/{MADE_UP}/files/{MADE_UP}", None),
    ],
)
def test_what_the_workspace_doesnt_hold_is_a_404(
    client: TestClient, world: World, method: str, path: str, body: dict[str, Any] | None
) -> None:
    # Requirements 1.10, 5.9 and 9.2: the fakes hold one bench, so another bench's ids are
    # among the made-up ones; the database's side is the isolation tests'.
    response = client.request(method, path, json=body)

    assert response.status_code == 404
    assert world.work.commits == 0


# --- The revisions it runs on ---------------------------------------------------------------


def test_a_link_and_an_unlink_answer_no_content_and_repeat_safely(
    client: TestClient, world: World
) -> None:
    # Requirements 3.1 and 3.2: a repeated link and a missing unlink write nothing.
    firmware = world.hold_firmware("Weather station")
    revision = world.directory.hold()
    path = f"{FIRMWARE}/{firmware.id}/revisions/{revision.revision_id}"

    linked = [client.put(path).status_code for _ in range(2)]
    runs_on = answered(client.get(f"{FIRMWARE}/{firmware.id}"))["runs_on"]
    unlinked = [client.delete(path).status_code for _ in range(2)]

    assert (linked, unlinked) == ([204, 204], [204, 204])
    assert [one["revision_id"] for one in runs_on] == [str(revision.revision_id)]
    assert world.work.links.saved == {}
    assert world.work.commits == 2


def test_linking_a_revision_the_workspace_doesnt_hold_is_a_404(
    client: TestClient, world: World
) -> None:
    # Requirement 3.7.
    firmware = world.hold_firmware("Weather station")

    response = client.put(f"{FIRMWARE}/{firmware.id}/revisions/{MADE_UP}")

    assert response.status_code == 404
    assert world.work.links.saved == {}


# --- Versions -------------------------------------------------------------------------------


def test_a_new_version_is_an_empty_draft_numbered_as_suggested(
    client: TestClient, world: World
) -> None:
    # Requirements 5.4, 5.5 and 5.8: 0.1.0 for a firmware with none, with its limits.
    firmware = world.hold_firmware("Weather station")

    body = answered(client.post(f"{FIRMWARE}/{firmware.id}/versions", json={}), 201)

    assert body == {
        "id": body["id"],
        "firmware_id": str(firmware.id),
        "version": "0.1.0",
        "status": "draft",
        "changelog": None,
        "based_on": None,
        "released_at": None,
        "created_at": STAMP,
        "updated_at": STAMP,
        "editable": True,
        "files": [],
        "size": 0,
        "size_limit": MAX_VERSION_BYTES,
        "file_limit": MAX_FILES,
    }


def test_a_version_started_from_another_holds_copies_of_its_files(
    client: TestClient, world: World
) -> None:
    # Requirements 5.1, 5.5 and 6.6: the number as typed, stored canonical; the base named,
    # and its own file left as it was.
    firmware = world.hold_firmware("Weather station")
    base = world.hold_version(firmware, "1.0.0", released=True)
    held = world.hold_file(base, "weather_station.ino", "void loop() {}\n")

    body = answered(
        client.post(
            f"{FIRMWARE}/{firmware.id}/versions",
            json={"version": " v1.1.0-RC.1 ", "from_version_id": str(base.id)},
        ),
        201,
    )

    [copy] = body["files"]
    assert (body["version"], body["based_on"]) == (
        "1.1.0-rc.1",
        {"id": str(base.id), "version": "1.0.0"},
    )
    assert (copy["path"], copy["content"]) == ("weather_station.ino", "void loop() {}\n")
    assert copy["id"] != str(held.id)
    assert world.work.sources.of(base.id) == [held]


def test_a_base_of_another_firmware_is_a_404(client: TestClient, world: World) -> None:
    # Requirement 5.9.
    firmware = world.hold_firmware("Weather station")
    other = world.hold_version(world.hold_firmware("Pico blink"), "1.0.0", released=True)

    response = client.post(
        f"{FIRMWARE}/{firmware.id}/versions", json={"from_version_id": str(other.id)}
    )

    assert response.status_code == 404
    assert world.work.commits == 0


def test_a_version_opens_with_its_files_sketches_first(client: TestClient, world: World) -> None:
    # Requirements 5.8 and 7.10: each file's text as stored, with its UTF-8 bytes and lines.
    version = world.hold_version(world.hold_firmware("Weather station"), "1.2.0")
    world.hold_file(version, "src/sensor.cpp", "// é\n")
    world.hold_file(version, "config.h", "#define SDA 21")
    world.hold_file(version, "Weather_station.ino")

    body = answered(client.get(f"{VERSIONS}/{version.id}"))

    assert [(file["path"], file["size"], file["lines"]) for file in body["files"]] == [
        ("Weather_station.ino", 0, 0),
        ("config.h", 14, 1),
        ("src/sensor.cpp", 6, 1),
    ]
    assert (body["size"], body["editable"]) == (20, True)


def test_a_draft_takes_a_new_number_and_changelog(client: TestClient, world: World) -> None:
    # Requirements 5.6 and 5.7: the changelog's line breaks kept and its ends trimmed.
    version = world.hold_version(world.hold_firmware("Weather station"), "1.2.0")

    body = answered(
        client.patch(
            f"{VERSIONS}/{version.id}",
            json={"version": "1.3.0", "changelog": " Averages three readings.\r\nSleeps. "},
        )
    )

    assert (body["version"], body["changelog"]) == (
        "1.3.0",
        "Averages three readings.\nSleeps.",
    )


def test_a_blank_changelog_reads_as_none(client: TestClient, world: World) -> None:
    version = world.hold_version(world.hold_firmware("Weather station"), "1.2.0")

    body = answered(
        client.patch(f"{VERSIONS}/{version.id}", json={"version": "1.2.0", "changelog": " \n "})
    )

    assert body["changelog"] is None


def test_a_released_draft_answers_its_release_date(client: TestClient, world: World) -> None:
    # Requirement 6.1: released when the request ran, and no longer editable.
    version = world.hold_version(world.hold_firmware("Weather station"), "1.0.0")
    world.hold_file(version, "sketch.ino", "void setup() {}\n")
    answered(
        client.patch(
            f"{VERSIONS}/{version.id}", json={"version": "1.0.0", "changelog": "First light."}
        )
    )
    world.clock.advance(timedelta(minutes=1))

    body = answered(client.post(f"{VERSIONS}/{version.id}/release"))

    assert (body["status"], body["released_at"], body["editable"]) == (
        "released",
        "2026-09-30T03:01:00Z",
        False,
    )
    assert [file["path"] for file in body["files"]] == ["sketch.ino"]


def test_deleting_a_base_keeps_the_versions_started_from_it(
    client: TestClient, world: World
) -> None:
    # Requirements 8.1 and 8.2: released or not, a version goes with its files.
    firmware = world.hold_firmware("Weather station")
    base = world.hold_version(firmware, "1.0.0", released=True)
    world.hold_file(base, "sketch.ino")
    later = world.hold_version(firmware, "1.1.0", based_on=base)

    deleted = client.delete(f"{VERSIONS}/{base.id}")

    assert deleted.status_code == 204
    assert answered(client.get(f"{VERSIONS}/{later.id}"))["based_on"] is None
    assert client.get(f"{VERSIONS}/{base.id}").status_code == 404
    assert world.work.sources.saved == {}


@pytest.mark.parametrize("typed", ["1.02.0", "1.0.0+build.5", "1.0", "1" * 65])
def test_a_number_the_grammar_doesnt_read_is_refused_on_the_version(
    client: TestClient, world: World, typed: str
) -> None:
    # Requirement 5.1, answered with its code: the router reads the number inside its refusal
    # handlers, so a bad one is never a 500.
    firmware = world.hold_firmware("Weather station")

    detail = refusal(
        client.post(f"{FIRMWARE}/{firmware.id}/versions", json={"version": typed}), 422
    )

    assert (detail["code"], detail["field"], detail["item"]) == (
        "invalid_version",
        "version",
        typed,
    )
    assert world.work.commits == 0


def test_a_number_another_version_holds_is_a_409(client: TestClient, world: World) -> None:
    # Requirement 5.2, compared canonical: `v1.0.0` is 1.0.0, started or renumbered.
    firmware = world.hold_firmware("Weather station")
    world.hold_version(firmware, "1.0.0", released=True)
    draft = world.hold_version(firmware, "1.1.0")

    started = client.post(f"{FIRMWARE}/{firmware.id}/versions", json={"version": "v1.0.0"})
    renumbered = client.patch(f"{VERSIONS}/{draft.id}", json={"version": "1.0.0"})

    for response in (started, renumbered):
        assert refusal(response, 409) == {
            "message": "this firmware already has a version 1.0.0",
            "code": "version_taken",
            "field": "version",
            "item": "1.0.0",
            "flashes": [],
        }
    assert world.work.commits == 0


def test_a_changelog_over_4000_characters_is_refused_on_it(
    client: TestClient, world: World
) -> None:
    # Requirement 5.6.
    version = world.hold_version(world.hold_firmware("Weather station"), "1.2.0")

    detail = refusal(
        client.patch(
            f"{VERSIONS}/{version.id}", json={"version": "1.2.0", "changelog": "x" * 4_001}
        ),
        422,
    )

    assert (detail["code"], detail["field"]) == ("invalid_changelog", "changelog")
    assert world.work.commits == 0


def test_a_draft_with_no_file_or_no_changelog_isnt_released(
    client: TestClient, world: World
) -> None:
    # Requirements 6.2 and 6.3: a 409 each, the second marked on the changelog.
    firmware = world.hold_firmware("Weather station")
    empty = world.hold_version(firmware, "1.0.0")
    unexplained = world.hold_version(firmware, "1.1.0")
    world.hold_file(unexplained, "sketch.ino")

    no_files = refusal(client.post(f"{VERSIONS}/{empty.id}/release"), 409)
    no_changelog = refusal(client.post(f"{VERSIONS}/{unexplained.id}/release"), 409)

    assert (no_files["code"], no_files["field"]) == ("no_files", None)
    assert (no_changelog["code"], no_changelog["field"]) == ("no_changelog", "changelog")
    assert world.work.commits == 0


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("PATCH", "", {"version": "1.0.0", "changelog": "What 1.0.0 changed."}),
        ("POST", "/release", None),
        ("POST", "/files", {"files": [{"path": "config.h", "content": ""}]}),
        ("PATCH", "/files/{file}", {"path": "sketch.ino", "content": "void loop() {}\n"}),
        ("DELETE", "/files/{file}", None),
    ],
)
def test_a_released_version_refuses_every_write(
    client: TestClient, world: World, method: str, suffix: str, body: dict[str, Any] | None
) -> None:
    # Requirements 6.4 and 6.5: a number in a board's log always means the same code, so even
    # an edit that would change nothing is refused, and nothing moves.
    version = world.hold_version(world.hold_firmware("Weather station"), "1.0.0", released=True)
    file = world.hold_file(version, "sketch.ino", "void setup() {}\n")
    before = world.snapshot()

    response = client.request(
        method, f"{VERSIONS}/{version.id}{suffix.format(file=file.id)}", json=body
    )

    detail = refusal(response, 409)
    assert (detail["code"], detail["field"], detail["item"]) == ("version_released", None, None)
    assert world.snapshot() == before
    assert world.work.commits == 0


# --- Source files ---------------------------------------------------------------------------


def test_files_are_added_in_one_batch_answered_in_the_versions_order(
    client: TestClient, world: World
) -> None:
    # Requirements 7.1, 7.2, 7.4 and 7.10: `\` read as `/`, CRLF read as LF, a tab and trailing
    # spaces kept, and no final line break added.
    version = world.hold_version(world.hold_firmware("Weather station"), "1.2.0")
    world.hold_file(version, "weather_station.ino", "void setup() {}\n")

    body = answered(
        client.post(
            files_of(version),
            json={
                "files": [
                    {"path": "src\\sensor.cpp", "content": "int sda() {\r\n\treturn 21;  \r\n}"},
                    {"path": "config.h", "content": "#define SDA 21\n"},
                ]
            },
        ),
        201,
    )

    assert [(file["path"], file["content"], file["lines"]) for file in body] == [
        ("config.h", "#define SDA 21\n", 1),
        ("src/sensor.cpp", "int sda() {\n\treturn 21;  \n}", 3),
    ]
    assert len(world.work.sources.saved) == 3
    assert world.work.commits == 1


def test_a_file_renamed_keeps_its_id(client: TestClient, world: World) -> None:
    # Requirement 7.8: the path and text replaced whole under the file's id.
    version = world.hold_version(world.hold_firmware("Weather station"), "1.2.0")
    file = world.hold_file(version, "sketch.ino", "void setup() {}\n")

    body = answered(
        client.patch(
            f"{files_of(version)}/{file.id}",
            json={"path": "weather_station.ino", "content": "void loop() {}\n"},
        )
    )

    assert body == {
        "id": str(file.id),
        "path": "weather_station.ino",
        "content": "void loop() {}\n",
        "size": 15,
        "lines": 1,
    }


def test_a_file_is_removed_and_one_under_another_version_is_a_404(
    client: TestClient, world: World
) -> None:
    # Requirements 7.9 and 7.11.
    firmware = world.hold_firmware("Weather station")
    version = world.hold_version(firmware, "1.2.0")
    other = world.hold_version(firmware, "2.0.0")
    file = world.hold_file(version, "sketch.ino")

    misplaced = client.delete(f"{files_of(other)}/{file.id}")
    removed = client.delete(f"{files_of(version)}/{file.id}")

    assert (misplaced.status_code, removed.status_code) == (404, 204)
    assert world.work.sources.saved == {}


@pytest.mark.parametrize(
    ("file", "expected"),
    [
        ({"path": "../secrets.h", "content": ""}, (422, "invalid_path", "path", "../secrets.h")),
        ({"path": "lib/con?.h", "content": ""}, (422, "invalid_path", "path", "lib/con?.h")),
        ({"path": "Sketch.INO", "content": ""}, (409, "path_taken", "path", "Sketch.INO")),
        ({"path": "sketch.ino/a.h", "content": ""}, (409, "path_taken", "path", "sketch.ino/a.h")),
        ({"path": "config.h", "content": "#de\x00"}, (422, "not_text", "content", "config.h")),
    ],
)
def test_a_refused_file_refuses_its_batch_naming_it(
    client: TestClient, world: World, file: dict[str, str], expected: tuple[int, str, str, str]
) -> None:
    # Requirements 7.1, 7.2, 7.3 and 7.5: the item is the path as typed, so the refusal names
    # the file among the batch's, and the batch's other file isn't kept either.
    status, code, field, item = expected
    version = world.hold_version(world.hold_firmware("Weather station"), "1.2.0")
    world.hold_file(version, "sketch.ino")
    batch = {"files": [{"path": "README.md", "content": "Fine on its own."}, file]}

    detail = refusal(client.post(files_of(version), json=batch), status)

    assert (detail["code"], detail["field"], detail["item"]) == (code, field, item)
    assert len(world.work.sources.saved) == 1
    assert world.work.commits == 0


@pytest.mark.parametrize(
    ("file", "expected"),
    [
        ({"path": "\ud800.h", "content": ""}, ("invalid_path", "path", "\\ud800.h")),
        (
            {"path": "config.h", "content": "#define SDA \ud800"},
            ("not_text", "content", "config.h"),
        ),
    ],
)
def test_half_a_surrogate_pair_is_refused_on_its_field_in_an_answer_that_encodes(
    client: TestClient, world: World, file: dict[str, str], expected: tuple[str, str, str]
) -> None:
    # Requirements 7.2 and 7.5: no bound in the request schema refuses the escape first, which
    # would answer a 500 for an input UTF-8 can't encode. The domain refuses it on its field,
    # naming the file, and writes it back as its escape.
    version = world.hold_version(world.hold_firmware("Weather station"), "1.2.0")
    batch = escaped_json({"files": [file]})

    detail = refusal(client.post(files_of(version), content=batch, headers=JSON_BODY), 422)

    assert (detail["code"], detail["field"], detail["item"]) == expected
    assert world.work.commits == 0


def test_a_rename_onto_another_files_path_is_a_409_naming_both(
    client: TestClient, world: World
) -> None:
    # Requirement 7.3 on an edit, in the domain's words; the file's own path in another case is
    # still its own.
    version = world.hold_version(world.hold_firmware("Weather station"), "1.2.0")
    world.hold_file(version, "config.h")
    file = world.hold_file(version, "sketch.ino")
    path = f"{files_of(version)}/{file.id}"

    recased = client.patch(path, json={"path": "SKETCH.ino", "content": ""})
    taken = client.patch(path, json={"path": "Config.h", "content": ""})

    assert recased.status_code == 200
    assert refusal(taken, 409) == {
        "message": "Config.h and config.h are one path to Windows and macOS",
        "code": "path_taken",
        "field": "path",
        "item": "Config.h",
        "flashes": [],
    }
    assert world.work.commits == 1


def test_a_version_holds_at_most_100_files(client: TestClient, world: World) -> None:
    # Requirement 7.6: a request may carry 100 files, but the version can't pass 100 either.
    version = world.hold_version(world.hold_firmware("Weather station"), "1.2.0")
    for n in range(MAX_FILES):
        world.hold_file(version, f"lib/part{n}.h")

    response = client.post(files_of(version), json={"files": [{"path": "one.h", "content": ""}]})

    assert refusal(response, 422) == {
        "message": "a version holds at most 100 files, not 101",
        "code": "too_many_files",
        "field": "files",
        "item": None,
        "flashes": [],
    }
    assert world.work.commits == 0


def test_a_version_past_its_bytes_says_how_much_room_is_left(
    client: TestClient, world: World
) -> None:
    # Requirement 7.7, counted in UTF-8: each "é" is two bytes.
    version = world.hold_version(world.hold_firmware("Weather station"), "1.2.0")
    world.hold_file(version, "data.h", "x" * (MAX_VERSION_BYTES - 3))

    response = client.post(files_of(version), json={"files": [{"path": "é.h", "content": "éé"}]})

    assert refusal(response, 422) == {
        "message": (
            "4 bytes won't fit: a version holds 1,048,576 bytes of source, and this one has 3 left"
        ),
        "code": "version_too_large",
        "field": "files",
        "item": None,
        "flashes": [],
    }
    assert world.work.commits == 0


def test_one_file_past_a_versions_bytes_says_how_much_room_is_left(
    client: TestClient, world: World
) -> None:
    # Requirement 7.7 for a single file over the whole limit: no bound in the request schema
    # answers it first with a generic 422.
    version = world.hold_version(world.hold_firmware("Weather station"), "1.2.0")
    world.hold_file(version, "sketch.ino", "void setup() {}\n")
    batch = {"files": [{"path": "data.h", "content": "x" * (MAX_VERSION_BYTES + 1)}]}

    response = client.post(files_of(version), json=batch)

    assert refusal(response, 422) == {
        "message": (
            "1,048,577 bytes won't fit: a version holds 1,048,576 bytes of source, and this one "
            "has 1,048,560 left"
        ),
        "code": "version_too_large",
        "field": "files",
        "item": None,
        "flashes": [],
    }
    assert world.work.commits == 0


@pytest.mark.parametrize("count", [0, MAX_FILES + 1])
def test_a_batch_carries_1_to_100_files(client: TestClient, world: World, count: int) -> None:
    # Decision 10: the request schema's own bounds, answered with FastAPI's list.
    version = world.hold_version(world.hold_firmware("Weather station"), "1.2.0")
    batch = {"files": [{"path": f"part{n}.h", "content": ""} for n in range(count)]}

    response = client.post(files_of(version), json=batch)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "files"]
    assert world.work.commits == 0


def test_the_wire_names_follow_their_enums() -> None:
    assert set(get_args(FrameworkName.__value__)) == {framework.value for framework in Framework}
    assert set(get_args(VersionStatusName.__value__)) == {status.value for status in VersionStatus}
    assert set(get_args(FirmwareRefusalCodeName.__value__)) == {
        code.value for code in FirmwareRefusal
    }
    assert set(get_args(FirmwareFieldName.__value__)) == {field.value for field in FirmwareField}
