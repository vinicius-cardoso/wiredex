"""Workspace isolation over the BOM tables, as the role the API logs in with.

The repository filters `workspace_id` itself; this is the gate underneath it (ADR 0007,
requirements 9.1 and 9.2): as `wiredex_app`, another workspace's lines and designators aren't
there to be read or written, filter or no filter, and the composite keys refuse a line filed
under another workspace's revision even where no policy applies.
"""

from collections.abc import AsyncIterator
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, insert, text, update
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from support.bom import a_line
from support.identity import NewIds
from support.projects import NOW
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.projects.domain.bom import LineQuantity
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import (
    PartId,
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    RevisionStatus,
    Tags,
    WorkspaceId,
)
from wiredex.projects.infrastructure.orm import bom_designators, bom_lines
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

MINE = WorkspaceId(uuid7())
THEIRS = WorkspaceId(uuid7())
RESISTOR = PartId(uuid7())


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
        await connection.execute(text("TRUNCATE revisions, projects CASCADE"))


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The API's role, with the API's engine: row security applies."""
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


def projects_work(engine: AsyncEngine, workspace_id: WorkspaceId) -> SqlProjectsUnitOfWork:
    return SqlProjectsUnitOfWork(create_session_factory(engine), workspace_id, NewIds())


def a_revision(workspace_id: WorkspaceId) -> tuple[Project, Revision]:
    project = Project(
        id=ProjectId(uuid7()),
        workspace_id=workspace_id,
        name=ProjectName("Weather station"),
        description=None,
        tags=Tags.none(),
        created_at=NOW,
        updated_at=NOW,
    )
    revision = Revision(
        id=RevisionId(uuid7()),
        workspace_id=workspace_id,
        project_id=project.id,
        label=RevisionLabel("A"),
        summary=None,
        notes=None,
        status=RevisionStatus.DRAFT,
        forked_from=None,
        created_at=NOW,
        updated_at=NOW,
    )
    return project, revision


async def seed(engine: AsyncEngine, workspace_id: WorkspaceId) -> Revision:
    """A project, its revision A and a line R1–R3 of it, all in the workspace."""
    project, revision = a_revision(workspace_id)
    async with projects_work(engine, workspace_id) as work:
        await work.projects.add(project)
        await work.revisions.add(revision)
        await work.bom_lines.add(a_line(revision, RESISTOR, "R1-3"))
        await work.commit()
    return revision


async def test_another_workspace_sees_none_of_my_bom(app: AsyncEngine) -> None:
    mine = await seed(app, MINE)

    async with projects_work(app, THEIRS) as work:
        assert (await work.bom_lines.of_revision(mine.id)).lines == ()
        assert (await work.bom_lines.uses_of(RESISTOR, 3)).total == 0
        # No WHERE at all: the policy is what keeps these from reaching my rows.
        assert await work.session.scalar(text("SELECT count(*) FROM bom_lines")) == 0
        assert await work.session.scalar(text("SELECT count(*) FROM bom_designators")) == 0

    async with projects_work(app, MINE) as work:
        assert len((await work.bom_lines.of_revision(mine.id)).lines) == 1
        assert (await work.bom_lines.uses_of(RESISTOR, 3)).total == 1


async def test_another_workspace_cant_change_or_delete_my_bom(
    app: AsyncEngine, admin: AsyncEngine
) -> None:
    await seed(app, MINE)

    async with projects_work(app, THEIRS) as work:
        # Blind writes, no WHERE at all: the policy scopes them to their own, empty, rows.
        await work.session.execute(update(bom_lines).values(notes=None, quantity=LineQuantity(1)))
        await work.session.execute(delete(bom_designators))
        await work.session.execute(delete(bom_lines))
        await work.commit()

    async with admin.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM bom_lines")) == 1
        assert await connection.scalar(text("SELECT count(*) FROM bom_designators")) == 3
        assert await connection.scalar(text("SELECT quantity FROM bom_lines")) == 3


async def test_a_line_written_into_my_workspace_from_another_is_refused(app: AsyncEngine) -> None:
    # Their transaction, my workspace on the row: the policy's WITH CHECK refuses it.
    mine = await seed(app, MINE)
    line = a_line(mine, RESISTOR, "R9")

    with pytest.raises(ProgrammingError, match="row-level security"):
        async with projects_work(app, THEIRS) as work:
            await work.session.execute(
                insert(bom_lines).values(
                    id=line.id,
                    workspace_id=MINE,
                    revision_id=mine.id,
                    part_id=RESISTOR,
                    quantity=LineQuantity(1),
                    created_at=NOW,
                )
            )


async def test_a_designator_written_into_my_workspace_from_another_is_refused(
    app: AsyncEngine,
) -> None:
    mine = await seed(app, MINE)
    async with projects_work(app, MINE) as work:
        (line,) = (await work.bom_lines.of_revision(mine.id)).lines

    with pytest.raises(ProgrammingError, match="row-level security"):
        async with projects_work(app, THEIRS) as work:
            await work.session.execute(
                insert(bom_designators).values(
                    workspace_id=MINE, revision_id=mine.id, line_id=line.id, designator="R9"
                )
            )


async def test_a_line_filed_under_another_workspaces_revision_is_refused(
    admin: AsyncEngine,
) -> None:
    # Requirement 9.2: as the owner, whom no policy narrows, only the composite key stops it.
    theirs = await seed(admin, THEIRS)

    with pytest.raises(IntegrityError, match="fk_bom_lines_workspace_id_revisions"):
        async with admin.begin() as connection:
            await connection.execute(
                insert(bom_lines).values(
                    id=uuid7(),
                    workspace_id=MINE,
                    revision_id=theirs.id,
                    part_id=RESISTOR,
                    quantity=LineQuantity(1),
                    created_at=NOW,
                )
            )
