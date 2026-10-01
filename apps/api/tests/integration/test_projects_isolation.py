"""Workspace isolation over the projects tables, as the role the API logs in with.

The repositories filter `workspace_id` themselves, but that is a promise the code makes. This
is the gate underneath it (ADR 0007, requirements 8.1 to 8.4): as `wiredex_app`, another
workspace's projects, revisions and tags aren't there to be read or written, filter or no
filter, and the composite key refuses a revision filed under another workspace's project even
when the row's own workspace passes the policy. The policies also read the workspace setting,
which ends with its transaction, so an edit answers with what it read before its commit.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid7

import httpx
import pytest
from fastapi import FastAPI, Request
from pydantic import SecretStr
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from support.identity import NewIds
from support.sql import committing
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.projects import projects_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.projects.api.router import create_router
from wiredex.projects.application.ports import TagCount
from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.project import Project, ProjectDetails
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import (
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    RevisionStatus,
    Tag,
    Tags,
    WorkspaceId,
)
from wiredex.projects.infrastructure.orm import revisions
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 27, 10, tzinfo=UTC)
MINE = WorkspaceId(uuid7())
THEIRS = WorkspaceId(uuid7())


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


def a_project(workspace_id: WorkspaceId, name: str = "Weather station") -> Project:
    return Project(
        id=ProjectId(uuid7()),
        workspace_id=workspace_id,
        name=ProjectName(name),
        description=None,
        tags=Tags.of(["esp32", "i2c"]),
        created_at=NOW,
        updated_at=NOW,
    )


def a_revision(workspace_id: WorkspaceId, project_id: ProjectId, label: str = "A") -> Revision:
    return Revision(
        id=RevisionId(uuid7()),
        workspace_id=workspace_id,
        project_id=project_id,
        label=RevisionLabel(label),
        summary=None,
        notes=None,
        status=RevisionStatus.DRAFT,
        forked_from=None,
        created_at=NOW,
        updated_at=NOW,
    )


async def seed_my_bench(engine: AsyncEngine) -> tuple[Project, Revision]:
    """One project with its revision A, both mine."""
    project = a_project(MINE)
    revision = a_revision(MINE, project.id)
    async with projects_work(engine, MINE) as work:
        await work.projects.add(project)
        await work.revisions.add(revision)
        await work.commit()
    return project, revision


async def names_and_labels(engine: AsyncEngine) -> tuple[list[str], list[str]]:
    async with engine.connect() as connection:
        names = await connection.scalars(text("SELECT name FROM projects ORDER BY name"))
        labels = await connection.scalars(text("SELECT label FROM revisions ORDER BY label"))
        return list(names), list(labels)


async def test_my_own_bench_is_readable(app: AsyncEngine) -> None:
    project, revision = await seed_my_bench(app)

    async with projects_work(app, MINE) as work:
        assert await work.projects.get(project.id) is not None
        assert [p.id for p in await work.projects.matching(ProjectFilter())] == [project.id]
        assert await work.projects.tag_counts() == [
            TagCount(Tag("esp32"), 1),
            TagCount(Tag("i2c"), 1),
        ]
        assert [r.id for r in (await work.revisions.of_project(project.id)).items] == [revision.id]


async def test_another_workspace_sees_none_of_it(app: AsyncEngine) -> None:
    # Requirements 8.2 and 8.3: by id, by name, in the list, in the tags, and every revision.
    project, revision = await seed_my_bench(app)

    async with projects_work(app, THEIRS) as work:
        assert await work.projects.get(project.id) is None
        assert await work.projects.locked(project.id) is None
        assert await work.projects.named(project.name) is None
        assert await work.projects.matching(ProjectFilter()) == []
        assert await work.projects.matching(ProjectFilter("weather")) == []
        assert await work.projects.matching(ProjectFilter(tags=Tags.of(["esp32"]))) == []
        assert await work.projects.tag_counts() == []
        assert await work.revisions.get(revision.id) is None
        assert (await work.revisions.of_project(project.id)).items == ()
        assert await work.revisions.of_projects([project.id]) == {}


async def test_a_read_without_a_filter_sees_one_workspace(app: AsyncEngine) -> None:
    await seed_my_bench(app)

    async with projects_work(app, THEIRS) as work:
        theirs = await work.session.scalar(
            text("SELECT (SELECT count(*) FROM projects) + (SELECT count(*) FROM revisions)")
        )
    async with projects_work(app, MINE) as work:
        mine = await work.session.scalar(
            text("SELECT (SELECT count(*) FROM projects) + (SELECT count(*) FROM revisions)")
        )
    assert (theirs, mine) == (0, 2)


async def test_a_project_cannot_be_written_into_another_workspace(app: AsyncEngine) -> None:
    # Tagged with my workspace, pushed through theirs: the policy's WITH CHECK refuses it.
    async with projects_work(app, THEIRS) as work:
        await work.projects.add(a_project(MINE))
        with pytest.raises(ProgrammingError, match="row-level security"):
            await work.commit()


async def test_a_revision_cannot_be_written_into_another_workspace(app: AsyncEngine) -> None:
    project, _ = await seed_my_bench(app)

    async with projects_work(app, THEIRS) as work:
        # `add` flushes, so the policy refuses the row there and then.
        with pytest.raises(ProgrammingError, match="row-level security"):
            await work.revisions.add(a_revision(MINE, project.id, "B"))


async def test_a_write_without_a_filter_cannot_touch_another_workspace(
    app: AsyncEngine, admin: AsyncEngine
) -> None:
    await seed_my_bench(app)

    async with projects_work(app, THEIRS) as work:
        # No WHERE at all: the policy is what keeps these from reaching my rows.
        await work.session.execute(text("UPDATE projects SET name = 'Stolen', tags = '{}'"))
        await work.session.execute(text("UPDATE revisions SET label = 'Z'"))
        await work.session.execute(text("DELETE FROM revisions"))
        await work.session.execute(text("DELETE FROM projects"))
        await work.clear()
        await work.commit()

    assert await names_and_labels(admin) == (["Weather station"], ["A"])


async def test_a_revision_under_another_workspaces_project_is_refused(app: AsyncEngine) -> None:
    """Requirement 8.4: the composite foreign key, which no policy is needed for.

    Their transaction and their `workspace_id` on the row, so the policy's WITH CHECK is
    satisfied, but pointing at my project. The pair `(workspace_id, project_id)` matches no
    project of theirs, and the database refuses it.
    """
    project, _ = await seed_my_bench(app)

    async with projects_work(app, THEIRS) as work:
        with pytest.raises(IntegrityError, match="fk_revisions_workspace_id_projects"):
            await work.revisions.add(a_revision(THEIRS, project.id, "B"))


async def test_even_the_owner_cannot_split_a_revision_from_its_project(
    admin: AsyncEngine,
) -> None:
    # The owner bypasses the policies, which is why the rule lives in a constraint.
    project, _ = await seed_my_bench(admin)

    planted = insert(revisions).values(
        id=uuid7(),
        workspace_id=THEIRS,
        project_id=project.id,
        label=RevisionLabel("B"),
        status=RevisionStatus.DRAFT,
        created_at=NOW,
        updated_at=NOW,
    )
    async with admin.connect() as connection:
        with pytest.raises(IntegrityError, match="fk_revisions_workspace_id_projects"):
            await connection.execute(planted)


# --- An edit's answer, read under the setting it was scoped by --------------------------------


async def my_bench(_request: Request) -> WorkspaceId:
    """What `bootstrap/app.py` builds from the session: the workspace this request acts in."""
    return MINE


def revision_ids(revisions: list[dict[str, str]]) -> list[str]:
    return [revision["id"] for revision in revisions]


async def test_an_edit_answers_with_the_projects_revisions_and_commits_only_a_change(
    app: AsyncEngine,
) -> None:
    # `set_config(…, true)` lasts as long as the transaction that ran it, so after the edit's
    # commit the policies see no workspace: the revisions have to be read before it.
    use_cases = projects_use_cases(create_session_factory(app))
    created = await use_cases.create_project(MINE, ProjectDetails(ProjectName("Weather station")))
    renamed = ProjectDetails(ProjectName("Greenhouse controller"), tags=Tags.of(["esp32"]))
    revision_a = [revision.id for revision in created.revisions.items]

    with committing(app) as edit:
        edited = await use_cases.update_project(MINE, created.project.id, renamed)
    with committing(app) as again:
        unchanged = await use_cases.update_project(MINE, created.project.id, renamed)

    assert edited.project.details == renamed
    assert [revision.id for revision in edited.revisions.items] == revision_a
    assert [revision.id for revision in unchanged.revisions.items] == revision_a
    # Requirement 1.5: the edit that changed nothing wrote nothing.
    assert (len(edit), len(again)) == (1, 0)


async def test_the_edit_route_answers_with_the_project_page(app: AsyncEngine) -> None:
    # The router reads a page without a latest revision as a project deleted meanwhile, so an
    # answer read after the commit came back a 404, though the edit was saved.
    api = FastAPI()
    use_cases = projects_use_cases(create_session_factory(app))
    api.include_router(create_router(use_cases, my_bench), prefix="/api")
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url="http://bench") as client:
        created = await client.post("/api/projects", json={"name": "Weather station"})
        assert created.status_code == 201, created.text
        project = created.json()
        edited = await client.patch(
            f"/api/projects/{project['id']}", json={"name": "Weather station", "tags": ["esp32"]}
        )

    assert edited.status_code == 200, edited.text
    page = edited.json()
    assert page["tags"] == ["esp32"]
    assert revision_ids(page["revisions"]) == revision_ids(project["revisions"])
    assert page["latest_revision_id"] == project["latest_revision_id"]


async def test_another_workspace_never_reaches_my_trash(app: AsyncEngine) -> None:
    # 16's requirements 8.1 and 8.2: as wiredex_app, their bench lists none of my trash, and
    # can neither restore nor delete for good a project of mine.
    project, _ = await seed_my_bench(app)
    async with projects_work(app, MINE) as work:
        mine = await work.projects.locked(project.id)
        assert mine is not None
        mine.move_to_trash(NOW)
        await work.commit()

    async with projects_work(app, THEIRS) as work:
        assert await work.projects.trashed(None, 50) == []
        assert await work.projects.in_trash(project.id) is None
        assert await work.projects.empty_trash() == 0
        await work.commit()

    async with projects_work(app, MINE) as work:
        assert [found.id for found in await work.projects.trashed(None, 50)] == [project.id]
