"""The attachment use cases over the in-memory files fakes.

The bench holds one part that exists (`world.part`) and a generous quota; a test tightens the
quota or adds a second part when a rule needs it. Uploads carry a real signature so the
sniff accepts them: a `%PDF-` prefix is the cheapest valid file, and distinct trailing bytes
make distinct files.
"""

import hashlib
from datetime import timedelta
from uuid import uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from support.files import BENCH, World
from wiredex.files.application.attachments import ORPHAN_GRACE, Upload
from wiredex.files.domain.errors import (
    AlreadyAttachedError,
    AttachmentNotFoundError,
    FilesError,
    QuotaExceededError,
    SubjectNotFoundError,
    UnsupportedFileTypeError,
)
from wiredex.files.domain.values import (
    AttachmentId,
    AttachmentKind,
    AttachmentTitle,
    MediaType,
    Sha256,
    Subject,
    SubjectKind,
)

pytestmark = pytest.mark.anyio


def a_pdf(
    body: bytes = b"one", title: str | None = None, filename: str = "datasheet.pdf"
) -> Upload:
    """A valid PDF upload: the signature the sniff wants, and `body` making it distinct."""
    return Upload(
        data=b"%PDF-" + body,
        filename=filename,
        kind=AttachmentKind.DATASHEET,
        title=title,
    )


# --- Attach -------------------------------------------------------------------


async def test_attaching_stores_the_file_and_returns_the_attachment() -> None:
    # Requirement 1.1: the attachment carries id, kind, title, media type, size and date.
    world = World()
    view = await world.attach(BENCH, world.part, a_pdf(title="BME280 datasheet"))

    assert str(view.attachment.title) == "BME280 datasheet"
    assert view.attachment.kind is AttachmentKind.DATASHEET
    assert str(view.file.media_type) == "application/pdf"
    assert int(view.file.size) == len(b"%PDF-one")
    assert view.attachment.created_at == world.clock.now()
    assert world.work.commits == 1
    assert world.work.opened_for == [BENCH]


async def test_no_title_takes_the_file_name() -> None:
    # Requirement 1.2: a missing title falls back to the uploaded file's name.
    world = World()
    view = await world.attach(BENCH, world.part, a_pdf(filename="BME280.pdf"))
    assert str(view.attachment.title) == "BME280.pdf"


async def test_the_same_bytes_are_stored_once() -> None:
    # Requirement 1.3: two parts, same bytes, one object and one file row.
    world = World()
    other = world.another_part()
    await world.attach(BENCH, world.part, a_pdf(b"shared"))
    await world.attach(BENCH, other, a_pdf(b"shared"))

    assert len(world.store.objects) == 1
    assert len(world.work.files.saved) == 1
    assert len(world.work.attachments.saved) == 2


async def test_the_same_file_twice_on_one_part_is_refused() -> None:
    # Requirement 1.4: the same bytes attach at most once per subject.
    world = World()
    await world.attach(BENCH, world.part, a_pdf(b"dup"))
    with pytest.raises(AlreadyAttachedError):
        await world.attach(BENCH, world.part, a_pdf(b"dup"))
    assert len(world.work.attachments.saved) == 1


async def test_attaching_to_a_missing_part_is_a_404_and_stores_nothing() -> None:
    # Requirement 1.5: a part that isn't ours is not found, and nothing is written.
    world = World()
    with pytest.raises(SubjectNotFoundError):
        await world.attach(BENCH, world.a_missing_part(), a_pdf())
    assert world.store.objects == {}
    assert world.work.files.saved == {}
    assert world.work.commits == 0


async def test_a_non_document_is_refused() -> None:
    # Requirement 2.3: only PDF, PNG, JPEG and WebP; an SVG-looking upload is 415.
    world = World()
    svg = Upload(data=b"<svg xmlns=", filename="x.svg", kind=AttachmentKind.IMAGE)
    with pytest.raises(UnsupportedFileTypeError):
        await world.attach(BENCH, world.part, svg)
    assert world.store.objects == {}


async def test_an_empty_file_is_refused() -> None:
    # Requirement 2.5: empty bytes don't sniff to a type, so they never reach FileSize.
    world = World()
    empty = Upload(data=b"", filename="x.pdf", kind=AttachmentKind.OTHER)
    with pytest.raises(FilesError):
        await world.attach(BENCH, world.part, empty)


async def test_an_upload_past_the_quota_is_refused_and_says_how_much_is_left() -> None:
    # Requirement 2.6: a refusal that names the space left, and stores nothing.
    world = World()
    world.quotas.limit = len(b"%PDF-first")  # room for exactly the first file
    await world.attach(BENCH, world.part, a_pdf(b"first"))
    before = dict(world.store.objects)

    with pytest.raises(QuotaExceededError) as raised:
        await world.attach(BENCH, world.another_part(), a_pdf(b"second-and-longer"))
    assert "left" in str(raised.value)
    assert world.store.objects == before


async def test_a_file_already_stored_does_not_count_against_the_quota_again() -> None:
    # Requirement 2.6 with 1.3: re-using stored bytes adds nothing, so a full quota still
    # lets the same file attach to another part.
    world = World()
    other = world.another_part()
    await world.attach(BENCH, world.part, a_pdf(b"shared"))
    world.quotas.limit = int((await world.list_attachments(BENCH, world.part))[0].file.size)

    view = await world.attach(BENCH, other, a_pdf(b"shared"))
    assert view.file.sha256 == (await world.list_attachments(BENCH, world.part))[0].file.sha256
    assert len(world.store.objects) == 1


# --- ListAttachments ----------------------------------------------------------


async def test_attachments_come_back_newest_first() -> None:
    # Requirement 1.6.
    world = World()
    first = await world.attach(BENCH, world.part, a_pdf(b"a", title="first"))
    world.clock.advance(timedelta(seconds=1))
    second = await world.attach(BENCH, world.part, a_pdf(b"b", title="second"))

    listed = await world.list_attachments(BENCH, world.part)
    assert [v.attachment.id for v in listed] == [second.attachment.id, first.attachment.id]


async def test_listing_a_part_with_none_is_empty() -> None:
    world = World()
    assert await world.list_attachments(BENCH, world.part) == []


# --- OpenAttachment -----------------------------------------------------------


async def test_opening_streams_the_bytes() -> None:
    # Requirement 3: the attachment, its file, and its bytes.
    world = World()
    view = await world.attach(BENCH, world.part, a_pdf(b"content"))

    opened = await world.open_attachment(BENCH, view.attachment.id)
    chunks = [chunk async for chunk in opened.stream]
    assert b"".join(chunks) == b"%PDF-content"
    assert opened.file.sha256 == view.file.sha256


async def test_opening_a_missing_attachment_is_a_404() -> None:
    # Requirement 3.4: another workspace's id is simply not found here.
    world = World()
    with pytest.raises(AttachmentNotFoundError):
        await world.open_attachment(BENCH, AttachmentId(uuid4()))


# --- ChangeAttachment ---------------------------------------------------------


async def test_changing_a_title_and_kind_commits() -> None:
    # Requirement 4.1: the change is stored, the file kept.
    world = World()
    view = await world.attach(BENCH, world.part, a_pdf())
    before = world.work.commits

    changed = await world.change_attachment(
        BENCH, view.attachment.id, AttachmentTitle("new"), AttachmentKind.OTHER
    )
    assert str(changed.title) == "new"
    assert changed.kind is AttachmentKind.OTHER
    assert world.work.commits == before + 1
    assert view.file.sha256 in world.work.files.saved


async def test_a_no_op_change_commits_nothing() -> None:
    world = World()
    view = await world.attach(BENCH, world.part, a_pdf(title="same"))
    before = world.work.commits
    await world.change_attachment(BENCH, view.attachment.id, AttachmentTitle("same"))
    assert world.work.commits == before


async def test_changing_a_missing_attachment_is_a_404() -> None:
    world = World()
    with pytest.raises(AttachmentNotFoundError):
        await world.change_attachment(BENCH, AttachmentId(uuid4()), AttachmentTitle("x"))


# --- Detach -------------------------------------------------------------------


async def test_detaching_the_last_user_removes_the_file_and_object() -> None:
    # Requirement 4.2: no other attachment uses it, so the file row and object go too.
    world = World()
    view = await world.attach(BENCH, world.part, a_pdf(b"only"))

    await world.detach(BENCH, view.attachment.id)

    assert world.work.attachments.saved == {}
    assert world.work.files.saved == {}
    assert world.store.objects == {}


async def test_detaching_keeps_a_file_another_attachment_still_uses() -> None:
    # Requirement 4.2: shared bytes survive while a second part still points at them.
    world = World()
    other = world.another_part()
    kept = await world.attach(BENCH, world.part, a_pdf(b"shared"))
    await world.attach(BENCH, other, a_pdf(b"shared"))

    await world.detach(BENCH, kept.attachment.id)

    assert kept.file.sha256 in world.work.files.saved
    assert len(world.store.objects) == 1


async def test_detaching_a_missing_attachment_is_a_404() -> None:
    world = World()
    with pytest.raises(AttachmentNotFoundError):
        await world.detach(BENCH, AttachmentId(uuid4()))


# --- ClearWorkspace -----------------------------------------------------------


async def test_clearing_removes_every_row_and_object() -> None:
    # Requirement 5.3: a demo reset wipes the workspace's files clean.
    world = World()
    other = world.another_part()
    await world.attach(BENCH, world.part, a_pdf(b"a"))
    await world.attach(BENCH, other, a_pdf(b"b"))

    await world.clear_workspace(BENCH)

    assert world.work.attachments.saved == {}
    assert world.work.files.saved == {}
    assert world.store.objects == {}


# --- PruneOrphans -------------------------------------------------------------


async def test_pruning_removes_attachments_of_a_deleted_part() -> None:
    # Requirement 4.4: a part is gone, its attachments and their now-unused file go.
    world = World()
    view = await world.attach(BENCH, world.part, a_pdf(b"a"))
    world.subjects.drop(BENCH, world.part)  # the part was deleted
    world.clock.advance(timedelta(hours=2))  # the nightly run, well after the upload

    await world.prune(BENCH)

    assert world.work.attachments.saved == {}
    assert world.work.files.saved == {}
    assert world.store.objects == {}
    assert view is not None


async def test_pruning_keeps_a_file_a_surviving_part_still_uses() -> None:
    # Requirement 4.4: a shared file whose other user survives keeps its row and object.
    world = World()
    other = world.another_part()
    await world.attach(BENCH, world.part, a_pdf(b"shared"))
    await world.attach(BENCH, other, a_pdf(b"shared"))
    world.subjects.drop(BENCH, world.part)  # only one of the two parts is gone

    await world.prune(BENCH)

    assert len(world.work.files.saved) == 1
    assert len(world.store.objects) == 1
    assert len(world.work.attachments.saved) == 1


async def test_pruning_removes_a_stray_object_no_row_names() -> None:
    # Requirement 4.4: an object left by a crash between put and the rows is swept.
    world = World()
    stray = f"workspaces/{BENCH}/sha256/{'a' * 64}"
    await world.store.put(stray, b"orphan", MediaType.PDF)
    world.clock.advance(ORPHAN_GRACE + timedelta(seconds=1))

    await world.prune(BENCH)

    assert stray not in world.store.objects


async def test_pruning_leaves_an_upload_in_flight_alone() -> None:
    # An upload writes its bytes before its rows: a young object with no row may be one still
    # being attached, and deleting it would leave its attachment pointing at nothing.
    world = World()
    in_flight = f"workspaces/{BENCH}/sha256/{'b' * 64}"
    await world.store.put(in_flight, b"arriving", MediaType.PDF)
    world.clock.advance(ORPHAN_GRACE - timedelta(seconds=1))

    await world.prune(BENCH)

    assert in_flight in world.store.objects


async def test_pruning_keeps_an_old_object_a_row_names() -> None:
    # Age alone never deletes: a file attached a year ago keeps its bytes.
    world = World()
    view = await world.attach(BENCH, world.part, a_pdf(b"kept"))
    world.clock.advance(timedelta(days=365))

    await world.prune(BENCH)

    assert len(world.store.objects) == 1
    assert view is not None


# --- Properties (design.md's correctness properties 2-4) ----------------------

# Distinct non-empty byte bodies, so a `%PDF-` prefix makes each a distinct valid file.
_bodies = st.lists(st.binary(min_size=1, max_size=32), min_size=1, max_size=8)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(bodies=_bodies)
async def test_property_same_bytes_are_one_file(bodies: list[bytes]) -> None:
    """Property 2: distinct byte strings become distinct objects; every file hashes its bytes.

    **Validates: Requirements 1.3, 5.2**
    """
    world = World()
    parts = [world.another_part() for _ in bodies]
    for part, body in zip(parts, bodies, strict=True):
        await world.attach(BENCH, part, Upload(b"%PDF-" + body, "f.pdf", AttachmentKind.OTHER))

    distinct = {b"%PDF-" + body for body in bodies}
    assert len(world.store.objects) == len(distinct)
    assert len(world.work.files.saved) == len(distinct)
    for key, data in world.store.objects.items():
        assert key.endswith(hashlib.sha256(data).hexdigest())


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(bodies=_bodies, limit=st.integers(min_value=1, max_value=400))
async def test_property_quota_is_never_exceeded(bodies: list[bytes], limit: int) -> None:
    """Property 3: stored size never passes the quota, and a refusal only when it would.

    **Validates: Requirements 2.6, 2.7**
    """
    world = World()
    world.quotas.limit = limit
    for body in bodies:
        part = world.another_part()
        upload = Upload(b"%PDF-" + body, "f.pdf", AttachmentKind.OTHER)
        used_before = await world.work.files.total_size()
        incoming = len(upload.data)
        digest = Sha256(hashlib.sha256(upload.data).hexdigest())
        already = await world.work.files.get(digest) is not None
        try:
            await world.attach(BENCH, part, upload)
        except QuotaExceededError:
            # Refused only when the new bytes wouldn't fit; a stored file adds nothing.
            assert not already
            assert used_before + incoming > limit
        assert await world.work.files.total_size() <= limit


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(bodies=_bodies)
async def test_property_removing_leaves_nothing_unused(bodies: list[bytes]) -> None:
    """Property 4: after the last detach of a file, no row and no object for it remain.

    **Validates: Requirements 4.2**
    """
    world = World()
    attached = []
    for body in bodies:
        upload = Upload(b"%PDF-" + body, "f.pdf", AttachmentKind.OTHER)
        # Same bytes attach once per part, so a fresh part per upload keeps every one.
        subject = Subject(SubjectKind.PART, uuid4())
        world.subjects.add(BENCH, subject)
        attached.append(await world.attach(BENCH, subject, upload))

    for view in attached:
        await world.detach(BENCH, view.attachment.id)

    assert world.work.attachments.saved == {}
    assert world.work.files.saved == {}
    assert world.store.objects == {}
