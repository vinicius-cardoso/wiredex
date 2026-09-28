"""The projects repositories and unit of work against a real PostgreSQL.

What only the database can answer: the folded unique indexes on names and labels, the tags
array read back as it was written and filtered with `@>`, the escaped `ILIKE` agreeing with
`ProjectFilter.matches`, the cascade and the `SET NULL` the keys carry, the status CHECK, the
project's row lock serializing changes to its revisions, and a rollback that leaves nothing of
a failed fork.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Self
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from support.identity import ManualClock, NewIds
from support.projects import NOW, CopyFailedError, FailingContent
from support.sql import counting
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.projects.application.ports import NewRevision, TagCount
from wiredex.projects.application.projects import (
    CreateProject,
    GetProject,
    ListProjects,
    UnitOfWorkFactory,
    UpdateProject,
)
from wiredex.projects.application.revisions import AddRevision, DeleteRevision, ForkRevision
from wiredex.projects.domain.errors import LastRevisionError
from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.project import Project, ProjectDetails
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import (
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    RevisionStatus,
    Summary,
    Tag,
    Tags,
    WorkspaceId,
)
from wiredex.projects.infrastructure.orm import revisions
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BENCH = WorkspaceId(uuid7())
OTHER = WorkspaceId(uuid7())


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(migrated_database_url))
    engine = create_engine(settings)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE revisions, projects CASCADE"))
    await engine.dispose()


def projects_work(engine: AsyncEngine, workspace_id: WorkspaceId = BENCH) -> SqlProjectsUnitOfWork:
    return SqlProjectsUnitOfWork(create_session_factory(engine), workspace_id)


def factory(engine: AsyncEngine) -> UnitOfWorkFactory:
    """What bootstrap will hand the use cases: one unit of work per call, for a workspace."""
    sessions = create_session_factory(engine)
    return lambda workspace_id: SqlProjectsUnitOfWork(sessions, workspace_id)


def a_project(name: str, *, tags: Sequence[str] = (), workspace_id: WorkspaceId = BENCH) -> Project:
    return Project(
        id=ProjectId(uuid7()),
        workspace_id=workspace_id,
        name=ProjectName(name),
        description=None,
        tags=Tags.of(tags),
        created_at=NOW,
        updated_at=NOW,
    )


def a_revision(
    project: Project,
    label: str,
    *,
    status: RevisionStatus = RevisionStatus.DRAFT,
    forked_from: Revision | None = None,
) -> Revision:
    return Revision(
        id=RevisionId(uuid7()),
        workspace_id=project.workspace_id,
        project_id=project.id,
        label=RevisionLabel(label),
        summary=None,
        notes=None,
        status=status,
        forked_from=None if forked_from is None else forked_from.id,
        created_at=NOW,
        updated_at=NOW,
    )


async def store(engine: AsyncEngine, project: Project, *held: Revision) -> None:
    """A project and its revisions, in one transaction of the project's workspace."""
    async with projects_work(engine, project.workspace_id) as work:
        await work.projects.add(project)
        for revision in held:
            await work.revisions.add(revision)
        await work.commit()


async def revision_count(engine: AsyncEngine) -> int:
    async with engine.connect() as connection:
        return int(await connection.scalar(select(func.count()).select_from(revisions)) or 0)


# --- The folded unique indexes ---------------------------------------------------------------


async def test_a_name_is_found_and_held_folded(engine: AsyncEngine) -> None:
    # `named` and `uq_projects_name` fold with the same `lower(name)` (decision 9, 1.3).
    station = a_project("Weather station")
    await store(engine, station)

    async with projects_work(engine) as work:
        found = await work.projects.named(ProjectName("WEATHER  station"))
        assert found is not None
        assert found.id == station.id
        assert await work.projects.named(ProjectName("Weather")) is None

    async with projects_work(engine) as work:
        await work.projects.add(a_project("weather STATION"))
        with pytest.raises(IntegrityError, match="uq_projects_name"):
            await work.commit()

    # Unique per workspace: another bench may use the name.
    await store(engine, a_project("Weather station", workspace_id=OTHER))


async def test_a_label_is_unique_folded_within_its_project(engine: AsyncEngine) -> None:
    station = a_project("Weather station")
    greenhouse = a_project("Greenhouse")
    await store(engine, station, a_revision(station, "B"))
    # Another project may use the same label.
    await store(engine, greenhouse, a_revision(greenhouse, "b"))

    async with projects_work(engine) as work:
        # `add` flushes, so the index refuses the row there and then.
        with pytest.raises(IntegrityError, match="uq_revisions_label"):
            await work.revisions.add(a_revision(station, "b"))


# --- Tags ------------------------------------------------------------------------------------


async def test_tags_are_read_back_as_they_were_stored(engine: AsyncEngine) -> None:
    # Requirement 2.5: the array round trip gives the same `Tags`, order and all.
    tagged = a_project("Weather station", tags=[" ESP32", "i2c", "esp32", "BME280"])
    bare = a_project("Greenhouse")
    await store(engine, tagged)
    await store(engine, bare)

    async with projects_work(engine) as work:
        read_tagged = await work.projects.get(tagged.id)
        read_bare = await work.projects.get(bare.id)

    assert read_tagged is not None
    assert read_bare is not None
    assert read_tagged.tags == Tags.of(["esp32", "i2c", "bme280"])
    assert read_tagged.tags.texts() == ("bme280", "esp32", "i2c")
    assert read_bare.tags == Tags.none()


async def test_the_tag_filter_wants_every_tag_and_the_counts_count_projects(
    engine: AsyncEngine,
) -> None:
    station = a_project("Weather station", tags=["esp32", "i2c"])
    greenhouse = a_project("Greenhouse", tags=["esp32", "relay"])
    await store(engine, station)
    await store(engine, greenhouse)
    await store(engine, a_project("Clock"))
    await store(engine, a_project("Elsewhere", tags=["esp32"], workspace_id=OTHER))

    async with projects_work(engine) as work:
        esp32 = await work.projects.matching(ProjectFilter(tags=Tags.of(["ESP32"])))
        both = await work.projects.matching(ProjectFilter(tags=Tags.of(["esp32", "i2c"])))
        none = await work.projects.matching(ProjectFilter(tags=Tags.of(["i2c", "relay"])))
        everything = await work.projects.matching(ProjectFilter())
        counts = await work.projects.tag_counts()

    assert {project.id for project in esp32} == {station.id, greenhouse.id}
    assert [project.id for project in both] == [station.id]
    assert none == []
    assert len(everything) == 3
    # Requirement 2.6: each tag once, alphabetical, counting this workspace's projects only.
    assert counts == [
        TagCount(Tag("esp32"), 2),
        TagCount(Tag("i2c"), 1),
        TagCount(Tag("relay"), 1),
    ]


# --- The name filter -------------------------------------------------------------------------


async def test_wildcards_in_the_name_filter_match_only_themselves(engine: AsyncEngine) -> None:
    # Requirement 3.3: `%` and `_` are characters, and the SQL agrees with `matches`.
    names = ("100% humidity", "1000 humidity", "a_b sensor", "axb sensor", "Weather station")
    held = [a_project(name) for name in names]
    for project in held:
        await store(engine, project)

    wanted = ("100%", "a_b", "%", "_", "WEATHER", "  station ", "humid", "nowhere")
    async with projects_work(engine) as work:
        found = {text: await work.projects.matching(ProjectFilter(text)) for text in wanted}

    for text_value, projects in found.items():
        expected = {p.id for p in held if ProjectFilter(text_value).matches(p)}
        assert {p.id for p in projects} == expected, text_value
    assert [p.name.value for p in found["100%"]] == ["100% humidity"]
    assert [p.name.value for p in found["a_b"]] == ["a_b sensor"]
    assert [p.name.value for p in found["%"]] == ["100% humidity"]
    assert [p.name.value for p in found["_"]] == ["a_b sensor"]


# --- The list, read through the use cases -----------------------------------------------------


async def test_the_list_opens_on_the_freshest_work(engine: AsyncEngine) -> None:
    # Requirement 3.2: a revision's change moves its project up without writing the project.
    clock = ManualClock(NOW)
    ids = NewIds()
    work = factory(engine)
    create = CreateProject(work, clock, ids)
    listing = ListProjects(work)

    old = await create(BENCH, ProjectDetails(ProjectName("Old")))
    clock.advance(timedelta(minutes=1))
    new = await create(BENCH, ProjectDetails(ProjectName("New")))
    assert [row.project.id for row in await listing(BENCH, ProjectFilter())] == [
        new.project.id,
        old.project.id,
    ]

    clock.advance(timedelta(minutes=1))
    added = await AddRevision(work, clock, ids)(
        BENCH, old.project.id, NewRevision(summary=Summary("perfboard"))
    )
    rows = await listing(BENCH, ProjectFilter())
    assert [row.project.id for row in rows] == [old.project.id, new.project.id]
    assert rows[0].latest.id == added.id
    assert rows[0].revision_count == 2
    assert rows[0].last_activity == clock.now()

    clock.advance(timedelta(minutes=1))
    await UpdateProject(work, clock)(BENCH, new.project.id, ProjectDetails(ProjectName("Newer")))
    assert [row.project.id for row in await listing(BENCH, ProjectFilter())] == [
        new.project.id,
        old.project.id,
    ]


async def test_a_page_and_the_list_cost_the_same_whatever_their_size(engine: AsyncEngine) -> None:
    # Requirement 11.3: two reads each, never one per project or per revision.
    clock = ManualClock(NOW)
    ids = NewIds()
    work = factory(engine)
    create = CreateProject(work, clock, ids)
    add = AddRevision(work, clock, ids)
    listing = ListProjects(work)
    page = GetProject(work)

    first = await create(BENCH, ProjectDetails(ProjectName("First")))
    with counting(engine) as small_list:
        await listing(BENCH, ProjectFilter())
    with counting(engine) as small_page:
        await page(BENCH, first.project.id)

    for name in ("Second", "Third", "Fourth"):
        await create(BENCH, ProjectDetails(ProjectName(name)))
    for _ in range(3):
        await add(BENCH, first.project.id, NewRevision())
    with counting(engine) as large_list:
        rows = await listing(BENCH, ProjectFilter())
    with counting(engine) as large_page:
        view = await page(BENCH, first.project.id)

    assert len(rows) == 4
    assert len(view.revisions.items) == 4
    assert len(large_list) == len(small_list)
    assert len(large_page) == len(small_page)


async def test_revisions_of_no_project_are_none(engine: AsyncEngine) -> None:
    async with projects_work(engine) as work:
        assert await work.revisions.of_projects([]) == {}


# --- What the keys and the CHECK do -----------------------------------------------------------


async def test_deleting_a_project_takes_its_revisions(engine: AsyncEngine) -> None:
    # Requirement 1.7, by the composite key's ON DELETE CASCADE.
    station = a_project("Weather station")
    kept = a_project("Greenhouse")
    await store(engine, station, a_revision(station, "A"), a_revision(station, "B"))
    await store(engine, kept, a_revision(kept, "A"))

    async with projects_work(engine) as work:
        found = await work.projects.get(station.id)
        assert found is not None
        await work.projects.remove(found)
        await work.commit()

    async with projects_work(engine) as work:
        assert await work.projects.get(station.id) is None
        assert (await work.revisions.of_project(station.id)).items == ()
        assert len((await work.revisions.of_project(kept.id)).items) == 1


async def test_deleting_a_source_keeps_its_fork_and_clears_where_it_came_from(
    engine: AsyncEngine,
) -> None:
    # Requirement 5.4, by `forked_from`'s ON DELETE SET NULL.
    station = a_project("Weather station")
    source = a_revision(station, "A")
    fork = a_revision(station, "B", forked_from=source)
    await store(engine, station, source, fork)

    async with projects_work(engine) as work:
        found = await work.revisions.get(source.id)
        assert found is not None
        await work.revisions.remove(found)
        await work.commit()

    async with projects_work(engine) as work:
        kept = await work.revisions.get(fork.id)
        assert await work.revisions.get(source.id) is None
    assert kept is not None
    assert kept.forked_from is None


@pytest.mark.parametrize("status", list(RevisionStatus))
async def test_each_of_the_four_statuses_is_stored(
    engine: AsyncEngine, status: RevisionStatus
) -> None:
    # Decision 5: 10-build-lifecycle writes the other three without a migration.
    station = a_project("Weather station")
    held = a_revision(station, "A", status=status)
    await store(engine, station, held)

    async with projects_work(engine) as work:
        found = await work.revisions.get(held.id)
    assert found is not None
    assert found.status is status


async def test_a_fifth_status_is_refused(engine: AsyncEngine) -> None:
    # Requirement 4.9: the CHECK over ADR 0003's four states.
    station = a_project("Weather station")
    held = a_revision(station, "A")
    await store(engine, station, held)

    async with projects_work(engine) as work:
        with pytest.raises(IntegrityError, match="ck_revisions_status"):
            await work.session.execute(
                text("UPDATE revisions SET status = 'archived' WHERE id = :id"),
                {"id": held.id},
            )


# --- The project's lock ----------------------------------------------------------------------


@asynccontextmanager
async def project_held(engine: AsyncEngine, project_id: ProjectId) -> AsyncIterator[None]:
    """The project's row locked by an outside transaction until the block ends.

    Left to themselves, two requests started together mostly run one after the other (the
    second is still getting its connection), which would hide a missing lock. Holding the row
    lines them both up at `Projects.locked` before either reads the siblings.
    """
    async with engine.begin() as holder:
        await holder.execute(
            text("SELECT id FROM projects WHERE id = :id FOR UPDATE"), {"id": project_id}
        )
        yield


async def until_waiting(engine: AsyncEngine, count: int) -> None:
    """Returns once `count` transactions wait on a lock, or fails: a change that never waits
    for the project's row isn't taking turns."""
    for _ in range(200):
        # A transaction each: pg_stat_activity is read once per transaction.
        async with engine.connect() as watcher:
            waiting = await watcher.scalar(
                text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'")
            )
        if (waiting or 0) >= count:
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"expected {count} transactions waiting for the project's lock")


async def test_two_deletes_of_the_last_two_revisions_leave_one(engine: AsyncEngine) -> None:
    # Requirement 5.5: without the lock both would see two revisions and both would go.
    clock = ManualClock(NOW)
    ids = NewIds()
    work = factory(engine)
    created = await CreateProject(work, clock, ids)(BENCH, ProjectDetails(ProjectName("Station")))
    first = created.revisions.items[0]
    clock.advance(timedelta(minutes=1))
    second = await AddRevision(work, clock, ids)(BENCH, created.project.id, NewRevision())

    delete = DeleteRevision(work, clock)
    async with project_held(engine, created.project.id):
        deletes = [
            asyncio.create_task(delete(BENCH, first.id)),
            asyncio.create_task(delete(BENCH, second.id)),
        ]
        await until_waiting(engine, 2)
    outcomes = await asyncio.gather(*deletes, return_exceptions=True)

    refused = [outcome for outcome in outcomes if isinstance(outcome, LastRevisionError)]
    assert len(refused) == 1
    assert outcomes.count(None) == 1
    view = await GetProject(work)(BENCH, created.project.id)
    assert len(view.revisions.items) == 1


async def test_two_forks_at_once_take_b_and_c(engine: AsyncEngine) -> None:
    # Requirement 5.5: each fork chooses its label once the other has committed.
    clock = ManualClock(NOW)
    ids = NewIds()
    work = factory(engine)
    created = await CreateProject(work, clock, ids)(BENCH, ProjectDetails(ProjectName("Station")))
    source = created.revisions.items[0]

    fork = ForkRevision(work, clock, ids)
    async with project_held(engine, created.project.id):
        tasks = [asyncio.create_task(fork(BENCH, source.id, NewRevision())) for _ in range(2)]
        await until_waiting(engine, 2)
    forks = await asyncio.gather(*tasks)

    assert sorted(revision.label.value for revision in forks) == ["B", "C"]
    assert all(revision.forked_from == source.id for revision in forks)
    view = await GetProject(work)(BENCH, created.project.id)
    assert [revision.label.value for revision in view.revisions.items] == ["A", "B", "C"]


# --- The unit of work ------------------------------------------------------------------------


class FailingForkUnitOfWork(SqlProjectsUnitOfWork):
    """The unit of work with a content that fails registered, as 09 will register its own."""

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.revision_contents = (FailingContent(),)
        return self


async def test_a_failing_content_leaves_no_revision(engine: AsyncEngine) -> None:
    # Requirement 6.4: the fork was flushed, then the copy raised, and the rollback took both.
    clock = ManualClock(NOW)
    ids = NewIds()
    created = await CreateProject(factory(engine), clock, ids)(
        BENCH, ProjectDetails(ProjectName("Station"))
    )
    sessions = create_session_factory(engine)
    failing = ForkRevision(
        lambda workspace_id: FailingForkUnitOfWork(sessions, workspace_id), clock, ids
    )

    with pytest.raises(CopyFailedError):
        await failing(BENCH, created.revisions.items[0].id, NewRevision())

    assert await revision_count(engine) == 1


async def test_a_revision_is_written_as_it_is_added(engine: AsyncEngine) -> None:
    # A content copying with Core finds the fork's row, and its project's, before any commit.
    station = a_project("Weather station")
    fork = a_revision(station, "A")
    async with projects_work(engine) as work:
        await work.projects.add(station)
        await work.revisions.add(fork)
        found = await work.session.scalar(
            text("SELECT count(*) FROM revisions WHERE id = :id"), {"id": fork.id}
        )
        assert found == 1
        assert work.revision_contents == ()
    assert await revision_count(engine) == 0


async def test_clear_empties_only_its_own_workspace(engine: AsyncEngine) -> None:
    mine = a_project("Weather station")
    theirs = a_project("Weather station", workspace_id=OTHER)
    await store(engine, mine, a_revision(mine, "A"))
    await store(engine, theirs, a_revision(theirs, "A"))

    async with projects_work(engine) as work:
        await work.clear()
        await work.commit()

    async with projects_work(engine) as work:
        assert await work.projects.matching(ProjectFilter()) == []
    async with projects_work(engine, OTHER) as work:
        assert [p.id for p in await work.projects.matching(ProjectFilter())] == [theirs.id]
    assert await revision_count(engine) == 1
