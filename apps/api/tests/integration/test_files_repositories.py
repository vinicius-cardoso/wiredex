"""The files repositories against a real PostgreSQL: the rows, the order, the composite key.

What only the database can answer: a `StoredFile` written with Core and read back whole, the
newest-first order the index carries, the counts `uses`, `unused` and `total_size` report,
and the composite foreign key refusing an attachment whose file belongs to another workspace.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4, uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.files.application.ports import FilesUnitOfWork
from wiredex.files.domain.entities import Attachment, StoredFile
from wiredex.files.domain.values import (
    AttachmentId,
    AttachmentKind,
    AttachmentTitle,
    FileSize,
    MediaType,
    Sha256,
    Subject,
    SubjectKind,
    WorkspaceId,
)
from wiredex.files.infrastructure.unit_of_work import SqlFilesUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 25, 10, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
OTHER = WorkspaceId(uuid7())
FILES_TABLES = "attachments, files"


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(migrated_database_url))
    engine = create_engine(settings)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {FILES_TABLES} CASCADE"))
    await engine.dispose()


def files(engine: AsyncEngine, workspace_id: WorkspaceId = BENCH) -> SqlFilesUnitOfWork:
    return SqlFilesUnitOfWork(create_session_factory(engine), workspace_id)


def a_sha(byte: int) -> Sha256:
    """A distinct valid SHA-256 per test file, without hashing real bytes here."""
    return Sha256(f"{byte:064x}")


def a_file(
    sha256: Sha256,
    workspace_id: WorkspaceId = BENCH,
    media_type: MediaType = MediaType.PDF,
    size: int = 1024,
    created_at: datetime = NOW,
) -> StoredFile:
    return StoredFile(workspace_id, sha256, media_type, FileSize(size), created_at)


def a_part() -> Subject:
    return Subject(SubjectKind.PART, uuid4())


def an_attachment(
    subject: Subject,
    sha256: Sha256,
    *,
    kind: AttachmentKind = AttachmentKind.DATASHEET,
    title: str = "Datasheet",
    created_at: datetime = NOW,
) -> Attachment:
    return Attachment(
        AttachmentId(uuid7()),
        BENCH,
        subject,
        sha256,
        kind,
        AttachmentTitle(title),
        created_at,
    )


async def test_the_unit_of_work_binds_the_files_repositories(engine: AsyncEngine) -> None:
    # Typed as the port the use cases take, so the real unit of work is checked against it.
    work: FilesUnitOfWork = files(engine)

    async with work as opened:
        assert await opened.files.total_size() == 0
        assert await opened.files.unused() == []
        assert await opened.attachments.of_subject(a_part()) == []


async def test_a_file_row_comes_back_whole(engine: AsyncEngine) -> None:
    stored = a_file(a_sha(1), media_type=MediaType.PNG, size=4096)

    async with files(engine) as work:
        await work.files.add(stored)
        await work.commit()

    async with files(engine) as work:
        read = await work.files.get(stored.sha256)

    assert read == stored
    assert read is not None
    assert read.media_type == MediaType.PNG
    assert int(read.size) == 4096


async def test_a_file_of_another_workspace_is_not_found(engine: AsyncEngine) -> None:
    stored = a_file(a_sha(1))

    async with files(engine) as work:
        await work.files.add(stored)
        await work.commit()

    # The same SHA-256, another bench: content-addressed per workspace, so it isn't ours.
    async with files(engine, OTHER) as work:
        assert await work.files.get(stored.sha256) is None


async def test_an_attachment_comes_back_whole(engine: AsyncEngine) -> None:
    part = a_part()
    sha = a_sha(1)

    async with files(engine) as work:
        await work.files.add(a_file(sha))
        attachment = an_attachment(part, sha, kind=AttachmentKind.IMAGE, title="A photo")
        await work.attachments.add(attachment)
        await work.commit()

    async with files(engine) as work:
        read = await work.attachments.get(attachment.id)

    assert read is not None
    assert read.subject == part
    assert read.sha256 == sha
    assert read.kind == AttachmentKind.IMAGE
    assert str(read.title) == "A photo"


async def test_a_subjects_attachments_come_newest_first(engine: AsyncEngine) -> None:
    # Requirement 1.6: the index carries the order, and the query reads it straight off.
    part = a_part()

    async with files(engine) as work:
        for n in range(3):
            sha = a_sha(n + 1)
            await work.files.add(a_file(sha))
            await work.attachments.add(
                an_attachment(part, sha, title=f"Doc {n}", created_at=NOW + timedelta(hours=n))
            )
        await work.commit()

    async with files(engine) as work:
        listed = await work.attachments.of_subject(part)

    assert [str(a.title) for a in listed] == ["Doc 2", "Doc 1", "Doc 0"]


async def test_find_locates_an_attachment_by_subject_and_bytes(engine: AsyncEngine) -> None:
    # What a re-attach checks (requirement 1.4): those bytes to that subject already?
    part = a_part()
    other_part = a_part()
    sha = a_sha(1)

    async with files(engine) as work:
        await work.files.add(a_file(sha))
        attachment = an_attachment(part, sha)
        await work.attachments.add(attachment)
        await work.commit()

    async with files(engine) as work:
        assert (await work.attachments.find(part, sha)) is not None
        assert (await work.attachments.find(other_part, sha)) is None
        assert (await work.attachments.find(part, a_sha(2))) is None


async def test_uses_counts_the_attachments_pointing_at_a_file(engine: AsyncEngine) -> None:
    # Requirement 4.2: a detach keeps the file while anything else still points at it.
    one = a_part()
    two = a_part()
    sha = a_sha(1)

    async with files(engine) as work:
        await work.files.add(a_file(sha))
        await work.attachments.add(an_attachment(one, sha))
        await work.attachments.add(an_attachment(two, sha))
        await work.commit()

    async with files(engine) as work:
        assert await work.attachments.uses(sha) == 2
        assert await work.attachments.uses(a_sha(2)) == 0


async def test_unused_lists_only_files_no_attachment_points_at(engine: AsyncEngine) -> None:
    # Requirement 4.2 and 4.4: removal and the prune both ask which files are orphaned.
    used = a_sha(1)
    orphan = a_sha(2)

    async with files(engine) as work:
        await work.files.add(a_file(used))
        await work.files.add(a_file(orphan))
        await work.attachments.add(an_attachment(a_part(), used))
        await work.commit()

    async with files(engine) as work:
        unused = await work.files.unused()

    assert [file.sha256 for file in unused] == [orphan]


async def test_total_size_sums_the_workspaces_files(engine: AsyncEngine) -> None:
    # Requirement 2.6: what an upload's quota is checked against.
    async with files(engine) as work:
        await work.files.add(a_file(a_sha(1), size=1000))
        await work.files.add(a_file(a_sha(2), size=2500))
        await work.commit()

    async with files(engine) as work:
        assert await work.files.total_size() == 3500

    # Another bench sums its own, which is none: the count is per workspace.
    async with files(engine, OTHER) as work:
        assert await work.files.total_size() == 0


async def test_subjects_are_the_distinct_subjects_of_the_attachments(engine: AsyncEngine) -> None:
    # Requirement 4.4: the prune tests each subject once, so duplicates collapse.
    one = a_part()
    two = a_part()

    async with files(engine) as work:
        await work.files.add(a_file(a_sha(1)))
        await work.files.add(a_file(a_sha(2)))
        await work.attachments.add(an_attachment(one, a_sha(1)))
        await work.attachments.add(an_attachment(one, a_sha(2)))
        await work.attachments.add(an_attachment(two, a_sha(1)))
        await work.commit()

    async with files(engine) as work:
        assert await work.attachments.subjects() == {one, two}


async def test_what_is_removed_is_gone(engine: AsyncEngine) -> None:
    part = a_part()
    sha = a_sha(1)

    async with files(engine) as work:
        await work.files.add(a_file(sha))
        attachment = an_attachment(part, sha)
        await work.attachments.add(attachment)
        await work.commit()

    async with files(engine) as work:
        stored = await work.attachments.get(attachment.id)
        assert stored is not None
        await work.attachments.remove(stored)
        file = await work.files.get(sha)
        assert file is not None
        await work.files.remove(file)
        await work.commit()

    async with files(engine) as work:
        assert await work.attachments.get(attachment.id) is None
        assert await work.files.get(sha) is None


async def test_an_attachment_cannot_name_a_file_of_another_workspace(engine: AsyncEngine) -> None:
    """The composite foreign key, which no policy is needed for (design's Data Models, ADR 0007).

    A file stored in OTHER; an attachment written in BENCH — its `workspace_id` is BENCH, so
    the policy's WITH CHECK is happy — but pointing at that SHA-256. The pair
    `(workspace_id, sha256)` matches no file of BENCH's, and the database refuses it.
    """
    theirs = a_sha(1)
    async with files(engine, OTHER) as work:
        await work.files.add(a_file(theirs, workspace_id=OTHER))
        await work.commit()

    async with files(engine, BENCH) as work:
        # Stamped BENCH (the helper's workspace), pointing at a SHA-256 only OTHER holds.
        await work.attachments.add(an_attachment(a_part(), theirs))
        with pytest.raises(IntegrityError, match="fk_attachments_workspace_id_files"):
            await work.commit()


async def test_queries_see_an_attachment_removed_in_the_same_unit_of_work(
    engine: AsyncEngine,
) -> None:
    # `Detach` and the prune remove an attachment and then ask, in the same transaction,
    # whether its file is still used. Those questions are Core queries, which SQLAlchemy
    # doesn't autoflush before, so the removal has to be visible to them already.
    file = a_file(a_sha(7))
    part = a_part()
    attachment = an_attachment(part, file.sha256)
    async with files(engine) as work:
        await work.files.add(file)
        await work.attachments.add(attachment)
        await work.commit()

    async with files(engine) as work:
        found = await work.attachments.get(attachment.id)
        assert found is not None
        await work.attachments.remove(found)

        assert await work.attachments.uses(file.sha256) == 0
        assert [f.sha256 for f in await work.files.unused()] == [file.sha256]
        assert await work.attachments.subjects() == set()
