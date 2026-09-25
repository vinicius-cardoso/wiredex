"""The files routes over the in-memory fakes: a bare FastAPI, no database, no real store.

The workspace dependency is a stub, because resolving it is identity's job and the
composition root's wiring (design §3); the ADR 0008 session and CSRF checks that come with
it are exercised in `tests/catalog/test_catalog_auth.py`, against the real app. What is
asserted here is the router's own contract: the multipart upload, the 413 that stops one
byte over the cap, the content headers and `?download=1`, and every row of the error table.
"""

from datetime import timedelta
from typing import Any, get_args

import pytest
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.testclient import TestClient

from support.files import BENCH, InMemoryFileStore, World
from wiredex.files.api.router import create_router
from wiredex.files.api.schemas import AttachmentKindName, MediaTypeName
from wiredex.files.application.attachments import Attach, FilesServices
from wiredex.files.domain.values import MAX_FILE_SIZE, AttachmentKind, MediaType, WorkspaceId

FILES = "/api/files"
MADE_UP = "0199aaaa-0000-7000-8000-000000000000"

# The smallest bytes each sniffer accepts: a PDF header, and the eight-byte PNG signature.
PDF = b"%PDF-1.4\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


async def the_bench(_request: Request) -> WorkspaceId:
    """What `bootstrap/app.py` builds from the session: the workspace this request acts in."""
    return BENCH


async def nobody(_request: Request) -> WorkspaceId:
    """A request with no valid session, which identity refuses before files is reached."""
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "log in first")


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def client(world: World) -> TestClient:
    return _client(world, the_bench)


def _client(world: World, workspace: Any) -> TestClient:
    app = FastAPI()
    app.include_router(create_router(world.files_use_cases(), workspace), prefix="/api")
    return TestClient(app)


def _upload(client: TestClient, world: World, **fields: Any) -> Any:
    """POST a multipart upload, defaulting to a small PDF on the world's seed part.

    Overrides come as keywords — `data`, `kind`, `filename`, `title`, `subject` — so a test
    changes just the one thing it is about, as catalog's `a_resistor` does with `**overrides`.
    """
    data: bytes = fields.get("data", PDF)
    filename: str = fields.get("filename", "datasheet.pdf")
    form: dict[str, str] = {
        "subject": fields.get("subject", str(world.part)),
        "kind": fields.get("kind", "datasheet"),
    }
    if (title := fields.get("title")) is not None:
        form["title"] = title
    return client.post(f"{FILES}/attachments", data=form, files={"file": (filename, data)})


def test_the_wire_kinds_and_media_types_match_the_enums() -> None:
    # A fifth kind or a new media type stops here until the client's union lists it too, the
    # way catalog's `test_every_kind_has_a_validator` keeps its own contract honest.
    assert set(get_args(AttachmentKindName.__value__)) == {k.value for k in AttachmentKind}
    assert set(get_args(MediaTypeName.__value__)) == {m.value for m in MediaType}


def test_an_upload_stores_the_file_and_answers_with_the_attachment(
    client: TestClient, world: World
) -> None:
    # Requirement 1.1: id, kind, title, media type, size and the time it was attached.
    response = _upload(client, world, title="MCU datasheet")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "datasheet"
    assert body["title"] == "MCU datasheet"
    assert body["media_type"] == "application/pdf"
    assert body["size"] == len(PDF)
    assert body["subject"] == str(world.part)
    assert body["content_url"] == f"/api/files/attachments/{body['id']}/content"
    assert world.store.objects  # the bytes were stored


def test_an_upload_with_no_title_takes_the_file_name(client: TestClient, world: World) -> None:
    # Requirement 1.2.
    body = _upload(client, world, filename="STM32F4.pdf").json()

    assert body["title"] == "STM32F4.pdf"


def test_the_attachments_of_a_part_come_back_newest_first(client: TestClient, world: World) -> None:
    # Requirement 1.6.
    _upload(client, world, data=PDF, filename="first.pdf")
    world.clock.advance(timedelta(seconds=1))
    _upload(client, world, data=PNG, kind="image", filename="second.png")

    response = client.get(f"{FILES}/attachments", params={"subject": str(world.part)})

    assert response.status_code == 200
    assert [a["title"] for a in response.json()] == ["second.png", "first.pdf"]


def test_the_same_file_on_the_same_part_twice_is_a_conflict(
    client: TestClient, world: World
) -> None:
    # Requirement 1.4.
    assert _upload(client, world).status_code == 201
    again = _upload(client, world)

    assert again.status_code == 409
    assert "already attached" in again.json()["detail"]


def test_an_upload_to_a_missing_part_is_not_found(client: TestClient, world: World) -> None:
    # Requirement 1.5: a part that isn't ours stores nothing.
    response = _upload(client, world, subject=str(world.a_missing_part()))

    assert response.status_code == 404
    assert world.store.objects == {}


def test_bytes_that_are_not_a_known_type_are_refused(client: TestClient, world: World) -> None:
    # Requirement 2.3: SVG and HTML included.
    response = _upload(client, world, data=b"<svg xmlns='...'></svg>", filename="logo.svg")

    assert response.status_code == 415
    assert "PDF, PNG, JPEG and WebP" in response.json()["detail"]


def test_an_empty_file_is_refused(client: TestClient, world: World) -> None:
    # Requirement 2.5: empty bytes sniff as nothing, so 415 (an unknown type), not stored.
    response = _upload(client, world, data=b"", filename="empty.pdf")

    assert response.status_code == 415
    assert world.store.objects == {}


def test_a_file_over_the_cap_is_refused_without_reading_on(
    client: TestClient, world: World
) -> None:
    # Requirement 2.4: 25 MiB + 1 byte is one too many, refused 413.
    too_big = b"%PDF-" + b"\x00" * (MAX_FILE_SIZE - 5 + 1)
    assert len(too_big) == MAX_FILE_SIZE + 1

    response = _upload(client, world, data=too_big, filename="huge.pdf")

    assert response.status_code == 413
    assert world.store.objects == {}


def test_a_file_exactly_at_the_cap_is_accepted(client: TestClient, world: World) -> None:
    # The boundary the other side of 413: 25 MiB on the nose is allowed.
    at_cap = b"%PDF-" + b"\x00" * (MAX_FILE_SIZE - 5)
    assert len(at_cap) == MAX_FILE_SIZE

    response = _upload(client, world, data=at_cap, filename="big.pdf")

    assert response.status_code == 201


def test_an_upload_past_the_quota_is_refused(client: TestClient, world: World) -> None:
    # Requirement 2.6: 413, and the message says how much room is left.
    world.quotas.limit = 10

    response = _upload(client, world, data=PDF)

    assert response.status_code == 413
    assert "left" in response.json()["detail"]


def test_content_streams_inline_with_its_headers(client: TestClient, world: World) -> None:
    # Requirement 3.1-3.3, 3.5: the bytes, the type, the title, cached privately, nosniff.
    created = _upload(client, world, data=PDF, title="MCU datasheet").json()

    response = client.get(f"{FILES}/attachments/{created['id']}/content")

    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == "inline; filename*=UTF-8''MCU%20datasheet"
    assert response.headers["content-length"] == str(len(PDF))
    assert response.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert response.headers["x-content-type-options"] == "nosniff"
    etag = response.headers["etag"]
    assert etag.startswith('"')
    assert etag.endswith('"')


def test_download_sends_the_content_as_an_attachment(client: TestClient, world: World) -> None:
    # Requirement 3.2: ?download=1 turns inline into a download.
    created = _upload(client, world).json()

    response = client.get(f"{FILES}/attachments/{created['id']}/content", params={"download": 1})

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")


def test_content_of_a_missing_attachment_is_not_found(client: TestClient) -> None:
    # Requirement 3.4: another workspace's id is simply not found here.
    response = client.get(f"{FILES}/attachments/{MADE_UP}/content")

    assert response.status_code == 404


def test_an_attachment_is_renamed_and_re_kinded(client: TestClient, world: World) -> None:
    # Requirement 4.1.
    created = _upload(client, world, kind="other").json()

    response = client.patch(
        f"{FILES}/attachments/{created['id']}",
        json={"title": "Renamed", "kind": "datasheet"},
    )

    assert response.status_code == 200
    assert (response.json()["title"], response.json()["kind"]) == ("Renamed", "datasheet")


def test_an_attachment_is_removed(client: TestClient, world: World) -> None:
    # Requirement 4.2: gone, and its lone file with it.
    created = _upload(client, world).json()

    assert client.delete(f"{FILES}/attachments/{created['id']}").status_code == 204
    assert client.get(f"{FILES}/attachments/{created['id']}/content").status_code == 404
    assert world.store.objects == {}


def test_a_malformed_subject_is_unprocessable(client: TestClient, world: World) -> None:
    # Anything the error table doesn't name falls through to 422, as catalog's does.
    response = _upload(client, world, subject="not-a-subject")

    assert response.status_code == 422


class BrokenStore(InMemoryFileStore):
    """A store whose write fails, standing in for an unreachable bucket.

    Only `put` is reached by an upload, so overriding it is enough; the rest is the
    in-memory store's, which keeps the object count and the reads a torn state would need.
    """

    async def put(self, key: str, data: bytes, media_type: MediaType) -> None:
        raise ConnectionError(f"unreachable: {key}, {len(data)} bytes of {media_type}")


def test_a_store_failure_on_upload_answers_503(world: World) -> None:
    # Design, Error Handling: a store that can't be reached is 503, not a files rule broken.
    services = FilesServices(BrokenStore(), world.subjects, world.quotas, world.clock, world.ids)
    world.attach = Attach(world.work.for_workspace, services)
    client = _client(world, the_bench)

    response = _upload(client, world)

    assert response.status_code == 503
    assert "can't be reached" in response.json()["detail"]


def test_a_request_with_no_session_never_reaches_files(world: World) -> None:
    # Requirement 6.2's files echo: identity refuses first, so no use case runs.
    logged_out = _client(world, nobody)

    response = logged_out.get(f"{FILES}/attachments", params={"subject": str(world.part)})

    assert response.status_code == 401
    assert world.work.opened_for == []


def test_a_missing_object_is_a_clean_error_not_a_broken_download(
    client: TestClient, world: World
) -> None:
    # The first chunk is read before any header goes out, so a lost object answers a whole
    # error response instead of a 200 cut off halfway.
    created = _upload(client, world).json()
    world.store.objects.clear()  # the bytes are gone; the rows still name them

    response = client.get(f"{FILES}/attachments/{created['id']}/content")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {"detail": "the file store can't be reached right now"}
