"""Workspace isolation over the files tables, as the role the API logs in with.

The repositories filter `workspace_id` themselves, but that is a promise the code makes.
This is the gate underneath it (ADR 0007): as `wiredex_app`, another workspace's files and
attachments aren't there to be read or written, filter or no filter.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4, uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import insert, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
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
from wiredex.files.infrastructure.orm import attachments
from wiredex.files.infrastructure.orm import files as files_table
from wiredex.files.infrastructure.unit_of_work import SqlFilesUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 25, 10, tzinfo=UTC)
MINE = WorkspaceId(uuid7())
THEIRS = WorkspaceId(uuid7())
FILES_TABLES = "attachments, files"
A_SHA = Sha256("a" * 64)


@pytest.fixture
async def admin(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema owner, which the policies don't apply to: it sees every workspace."""
    engine = create_async_engine(migrated_database_url)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean(admin: AsyncEngine) -> AsyncIterator[None]:
    """Emptied by the owner afterwards: the app role is granted no TRUNCATE."""
    yield
    async with admin.begin() as connection:
        await connection.execute(text(f"TRUNCATE {FILES_TABLES} CASCADE"))


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The API's role, with the API's engine: row security applies."""
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


def files(engine: AsyncEngine, workspace_id: WorkspaceId) -> SqlFilesUnitOfWork:
    return SqlFilesUnitOfWork(create_session_factory(engine), workspace_id)


async def seed_my_bench(engine: AsyncEngine) -> tuple[StoredFile, Attachment]:
    """One file and one attachment, both mine."""
    file = StoredFile(MINE, A_SHA, MediaType.PDF, FileSize(2048), NOW)
    attachment = Attachment(
        AttachmentId(uuid7()),
        MINE,
        Subject(SubjectKind.PART, uuid4()),
        A_SHA,
        AttachmentKind.DATASHEET,
        AttachmentTitle("Datasheet"),
        NOW,
    )
    async with files(engine, MINE) as work:
        await work.files.add(file)
        await work.attachments.add(attachment)
        await work.commit()
    return file, attachment


async def file_shas(engine: AsyncEngine) -> list[str]:
    """Every file in the table, read by the owner: what the policies were holding back."""
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT sha256 FROM files ORDER BY sha256"))
        return list(rows.scalars())


async def attachment_titles(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT title FROM attachments ORDER BY title"))
        return list(rows.scalars())


async def test_my_own_files_are_readable(app: AsyncEngine) -> None:
    file, attachment = await seed_my_bench(app)

    async with files(app, MINE) as work:
        assert await work.files.get(A_SHA) == file
        assert await work.files.total_size() == 2048
        found = await work.attachments.get(attachment.id)
        assert found is not None
        assert found.subject == attachment.subject
        assert await work.attachments.of_subject(attachment.subject) == [found]


async def test_another_workspace_sees_none_of_it(app: AsyncEngine) -> None:
    _, attachment = await seed_my_bench(app)

    async with files(app, THEIRS) as work:
        assert await work.files.get(A_SHA) is None
        assert await work.files.total_size() == 0
        assert await work.files.unused() == []
        # By id, so another workspace's id is simply not found.
        assert await work.attachments.get(attachment.id) is None
        assert await work.attachments.of_subject(attachment.subject) == []
        assert await work.attachments.uses(A_SHA) == 0
        assert await work.attachments.subjects() == set()


async def test_a_file_cannot_be_written_into_another_workspace(app: AsyncEngine) -> None:
    # A row stamped MINE, written in a transaction opened for THEIRS: the repository always
    # stamps its own workspace, so this is a raw INSERT, the way a bug or a bare statement
    # would try it. The policy's WITH CHECK refuses a row outside the transaction's workspace.
    planted = insert(files_table).values(
        workspace_id=MINE,
        sha256=A_SHA,
        media_type=MediaType.PDF,
        size=FileSize(2048),
        created_at=NOW,
    )

    async with files(app, THEIRS) as work:
        with pytest.raises(ProgrammingError, match="row-level security"):
            await work.session.execute(planted)


async def test_an_attachment_cannot_be_written_into_another_workspace(app: AsyncEngine) -> None:
    # A file THEIRS may hold, then a raw attachment INSERT stamped MINE: the row lands outside
    # the transaction's workspace, and the policy refuses it.
    async with files(app, THEIRS) as work:
        await work.files.add(StoredFile(THEIRS, A_SHA, MediaType.PDF, FileSize(2048), NOW))
        await work.commit()

    planted = insert(attachments).values(
        id=uuid7(),
        workspace_id=MINE,
        subject_kind=SubjectKind.PART,
        subject_id=uuid4(),
        sha256=A_SHA,
        kind=AttachmentKind.DATASHEET,
        title=AttachmentTitle("Planted"),
        created_at=NOW,
    )
    async with files(app, THEIRS) as work:
        with pytest.raises(ProgrammingError, match="row-level security"):
            await work.session.execute(planted)


async def test_a_write_without_a_filter_cannot_touch_another_workspace(
    app: AsyncEngine, admin: AsyncEngine
) -> None:
    await seed_my_bench(app)

    async with files(app, THEIRS) as work:
        # No WHERE at all: the policy is what keeps these from reaching my rows.
        await work.session.execute(text("UPDATE attachments SET title = 'Stolen'"))
        await work.session.execute(text("DELETE FROM attachments"))
        await work.session.execute(text("DELETE FROM files"))
        await work.commit()

    assert await file_shas(admin) == [A_SHA.value]
    assert await attachment_titles(admin) == ["Datasheet"]


async def test_a_read_without_a_filter_sees_one_workspace(app: AsyncEngine) -> None:
    await seed_my_bench(app)

    async with files(app, THEIRS) as work:
        theirs = await work.session.scalar(text("SELECT count(*) FROM files"))

    async with files(app, MINE) as work:
        mine = await work.session.scalar(text("SELECT count(*) FROM files"))

    assert (theirs, mine) == (0, 1)
