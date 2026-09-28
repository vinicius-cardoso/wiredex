"""BOM lines and their designators against a real PostgreSQL.

What only the database can answer: the lines and designators read back as written and in
order, an edit that leaves the rows of the designators it kept alone, the primary key and the
composite keys refusing what the domain would never write, the cascades, `uses_of`'s order
and count, the project's lock serializing two writes to one BOM and a write against a status
change, and a fork's copy riding the fork's one transaction.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from typing import Self
from uuid import UUID, uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import TextClause, insert, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from support.bom import a_line, facts_of
from support.identity import ManualClock, NewIds
from support.projects import NOW, CopyFailedError, FailingContent, FakePartLookup
from support.sql import committing, counting
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.projects.application.bom import AddBomLine, BomUnitOfWorkFactory, UpdateBomLine
from wiredex.projects.application.ports import NewBomLine, NewRevision
from wiredex.projects.application.revisions import ForkRevision
from wiredex.projects.domain.bom import BomLine, BomNotes, LineContent
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.errors import DesignatorTakenError, RevisionContentLockedError
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
from wiredex.projects.infrastructure.orm import bom_designators, revisions
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BENCH = WorkspaceId(uuid7())
OTHER = WorkspaceId(uuid7())
RESISTOR, SENSOR, WIRE = (PartId(uuid7()) for _ in range(3))
# What 10-build-lifecycle's reserve will do to a revision, done by hand while a write waits.
RESERVE = text("UPDATE revisions SET status = 'reserved' WHERE id = :id")


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(migrated_database_url))
    engine = create_engine(settings)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE revisions, projects CASCADE"))
    await engine.dispose()


def projects_work(engine: AsyncEngine, workspace_id: WorkspaceId = BENCH) -> SqlProjectsUnitOfWork:
    return SqlProjectsUnitOfWork(create_session_factory(engine), workspace_id, NewIds())


def factory(engine: AsyncEngine) -> BomUnitOfWorkFactory:
    sessions = create_session_factory(engine)
    ids = NewIds()
    return lambda workspace_id: SqlProjectsUnitOfWork(sessions, workspace_id, ids)


def a_project(name: str = "Weather station", workspace_id: WorkspaceId = BENCH) -> Project:
    return Project(
        id=ProjectId(uuid7()),
        workspace_id=workspace_id,
        name=ProjectName(name),
        description=None,
        tags=Tags.none(),
        created_at=NOW,
        updated_at=NOW,
    )


def a_revision(project: Project, label: str = "A", *, minutes: int = 0) -> Revision:
    when = NOW + timedelta(minutes=minutes)
    return Revision(
        id=RevisionId(uuid7()),
        workspace_id=project.workspace_id,
        project_id=project.id,
        label=RevisionLabel(label),
        summary=None,
        notes=None,
        status=RevisionStatus.DRAFT,
        forked_from=None,
        created_at=when,
        updated_at=when,
    )


async def store(engine: AsyncEngine, project: Project, *held: Revision) -> None:
    async with projects_work(engine, project.workspace_id) as work:
        await work.projects.add(project)
        for revision in held:
            await work.revisions.add(revision)
        await work.commit()


async def stored_revision(engine: AsyncEngine, name: str = "Weather station") -> Revision:
    project = a_project(name)
    revision = a_revision(project)
    await store(engine, project, revision)
    return revision


async def add_lines(engine: AsyncEngine, *lines: BomLine) -> None:
    async with projects_work(engine, lines[0].workspace_id) as work:
        await work.bom_lines.add_all(lines)
        await work.commit()


async def read_bom(engine: AsyncEngine, revision: Revision) -> tuple[BomLine, ...]:
    async with projects_work(engine, revision.workspace_id) as work:
        return (await work.bom_lines.of_revision(revision.id)).lines


async def count(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as connection:
        found = await connection.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
        return int(found or 0)


# --- Reading and writing ----------------------------------------------------------------------


async def test_lines_and_designators_read_back_equal_and_in_order(engine: AsyncEngine) -> None:
    revision = await stored_revision(engine)
    sensor = a_line(revision, SENSOR, "U1", minutes=2)
    resistors = a_line(revision, RESISTOR, "r1-4", minutes=1)
    wire = a_line(revision, WIRE, quantity=1, minutes=3)
    wire = wire.revised(replace(wire.content, notes=BomNotes("about 2 m of jumpers")))
    await add_lines(engine, sensor, resistors, wire)

    assert await read_bom(engine, revision) == (resistors, sensor, wire)


async def test_lines_sharing_a_date_keep_the_order_of_their_ids(engine: AsyncEngine) -> None:
    revision = await stored_revision(engine)
    lines = [a_line(revision, RESISTOR, f"R{number}") for number in range(1, 6)]
    await add_lines(engine, *reversed(lines))

    assert await read_bom(engine, revision) == tuple(lines)


async def test_a_bom_is_read_in_two_statements_and_written_in_two(engine: AsyncEngine) -> None:
    revision = await stored_revision(engine)
    lines = [a_line(revision, RESISTOR, f"R{number}, C{number}") for number in range(1, 31)]

    async with projects_work(engine) as work:
        with counting(engine) as written:
            await work.bom_lines.add_all(lines)
        await work.commit()
    async with projects_work(engine) as work:
        with counting(engine) as read:
            bom = await work.bom_lines.of_revision(revision.id)

    assert len(written) == 2
    assert len(read) == 2
    assert len(bom.lines) == 30


async def test_an_edit_keeps_the_rows_of_the_designators_it_kept(engine: AsyncEngine) -> None:
    # Decision 8: what 11 hangs off R2 and R3 survives an edit from R1–R3 to R2–R4.
    revision = await stored_revision(engine)
    before = a_line(revision, RESISTOR, "R1-3")
    await add_lines(engine, before)
    versions = await designator_versions(engine, before.id)

    after = before.revised(
        LineContent.of(SENSOR, Designators.parse("R2-4"), None, BomNotes("divider"))
    )
    async with projects_work(engine) as work:
        await work.bom_lines.update(before, after)
        await work.commit()

    now = await designator_versions(engine, before.id)
    assert set(now) == {"R2", "R3", "R4"}
    assert (now["R2"], now["R3"]) == (versions["R2"], versions["R3"])
    assert await read_bom(engine, revision) == (after,)


async def designator_versions(engine: AsyncEngine, line_id: UUID) -> dict[str, str]:
    """Each designator row's `xmin`: the transaction that last wrote it."""
    async with engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT designator, xmin::text FROM bom_designators WHERE line_id = :line"),
            {"line": line_id},
        )
        return {str(row.designator): str(row.xmin) for row in rows}


async def test_a_line_is_removed_with_its_designators(engine: AsyncEngine) -> None:
    revision = await stored_revision(engine)
    line = a_line(revision, RESISTOR, "R1-3")
    kept = a_line(revision, SENSOR, "U1", minutes=1)
    await add_lines(engine, line, kept)

    async with projects_work(engine) as work:
        await work.bom_lines.remove(line)
        await work.commit()

    assert await read_bom(engine, revision) == (kept,)
    assert await count(engine, "bom_designators") == 1


# --- What the keys refuse ---------------------------------------------------------------------


async def test_a_designator_twice_in_a_revision_is_refused_by_the_key(engine: AsyncEngine) -> None:
    # Decision 8: should a write ever skip the lock, the primary key still refuses it.
    revision = await stored_revision(engine)
    await add_lines(engine, a_line(revision, RESISTOR, "R1"))

    with pytest.raises(IntegrityError, match="pk_bom_designators"):
        await add_lines(engine, a_line(revision, SENSOR, "R1", minutes=1))
    assert await count(engine, "bom_lines") == 1


async def test_a_designator_filed_under_another_revisions_line_is_refused(
    engine: AsyncEngine,
) -> None:
    project = a_project()
    first, second = a_revision(project, "A"), a_revision(project, "B", minutes=1)
    await store(engine, project, first, second)
    line = a_line(first, RESISTOR, "R1")
    await add_lines(engine, line)

    with pytest.raises(IntegrityError, match="fk_bom_designators_workspace_id_bom_lines"):
        async with engine.begin() as connection:
            await connection.execute(
                insert(bom_designators).values(
                    workspace_id=BENCH, revision_id=second.id, line_id=line.id, designator="R2"
                )
            )


async def test_the_database_refuses_a_designator_that_isnt_canonical(engine: AsyncEngine) -> None:
    revision = await stored_revision(engine)
    line = a_line(revision, RESISTOR, "R1")
    await add_lines(engine, line)

    with pytest.raises(IntegrityError, match="ck_bom_designators_canonical"):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO bom_designators (workspace_id, revision_id, line_id, designator)"
                    " VALUES (:workspace, :revision, :line, 'R01')"
                ),
                {"workspace": BENCH, "revision": revision.id, "line": line.id},
            )


async def test_the_cascades_from_a_revision_and_a_project(engine: AsyncEngine) -> None:
    project = a_project()
    first, second = a_revision(project, "A"), a_revision(project, "B", minutes=1)
    await store(engine, project, first, second)
    await add_lines(engine, a_line(first, RESISTOR, "R1, R2"))
    await add_lines(engine, a_line(second, RESISTOR, "R1"))

    async with projects_work(engine) as work:
        await work.revisions.remove(second)
        await work.commit()
    assert (await count(engine, "bom_lines"), await count(engine, "bom_designators")) == (1, 2)

    async with projects_work(engine) as work:
        found = await work.projects.get(project.id)
        assert found is not None
        await work.projects.remove(found)
        await work.commit()
    assert (await count(engine, "bom_lines"), await count(engine, "bom_designators")) == (0, 0)


# --- Part uses ----------------------------------------------------------------------------------


async def test_uses_of_a_part_across_two_projects(engine: AsyncEngine) -> None:
    station, greenhouse = a_project("weather station"), a_project("Greenhouse controller")
    station_a, station_b = a_revision(station, "A"), a_revision(station, "B", minutes=1)
    greenhouse_a = a_revision(greenhouse, "A", minutes=2)
    await store(engine, station, station_a, station_b)
    await store(engine, greenhouse, greenhouse_a)
    await add_lines(
        engine,
        a_line(station_b, RESISTOR, "R1"),
        a_line(station_b, RESISTOR, "R2", minutes=1),
        a_line(station_a, RESISTOR, "R1"),
        a_line(greenhouse_a, RESISTOR, "R1-3"),
        a_line(greenhouse_a, SENSOR, "U1"),
    )

    async with projects_work(engine) as work:
        found = await work.bom_lines.uses_of(RESISTOR, 2)
        every = await work.bom_lines.uses_of(RESISTOR, 3)
        none = await work.bom_lines.uses_of(WIRE, 3)

    assert found.total == 3
    assert [(str(use.project_name), str(use.revision_label)) for use in every.uses] == [
        ("Greenhouse controller", "A"),
        ("weather station", "A"),
        ("weather station", "B"),
    ]
    assert found.uses == every.uses[:2]
    assert found.uses[0].project_id == greenhouse.id
    assert found.uses[0].revision_id == greenhouse_a.id
    assert (none.uses, none.total) == ((), 0)


# --- The project's lock --------------------------------------------------------------------------


@asynccontextmanager
async def project_held(
    engine: AsyncEngine, project_id: ProjectId, *, then: TextClause | None = None
) -> AsyncIterator[None]:
    """The project's row locked by an outside transaction until the block ends, which also
    runs `then` in that transaction, so it commits as the lock is released."""
    async with engine.begin() as holder:
        await holder.execute(
            text("SELECT id FROM projects WHERE id = :id FOR UPDATE"), {"id": project_id}
        )
        if then is not None:
            await holder.execute(then)
        yield


async def until_waiting(engine: AsyncEngine, expected: int) -> None:
    for _ in range(200):
        async with engine.connect() as watcher:
            waiting = await watcher.scalar(
                text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'")
            )
        if (waiting or 0) >= expected:
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"expected {expected} transactions waiting for the project's lock")


def adding(engine: AsyncEngine) -> tuple[AddBomLine, FakePartLookup]:
    parts = FakePartLookup()
    return AddBomLine(factory(engine), parts, ManualClock(NOW), NewIds()), parts


async def test_two_adds_claiming_r1_leave_one_line(engine: AsyncEngine) -> None:
    # Requirement 5.4: the second reads the BOM once the first has committed, and answers 409.
    revision = await stored_revision(engine)
    add, parts = adding(engine)
    resistor, capacitor = parts.hold("4k7"), parts.hold("100n")

    async with project_held(engine, revision.project_id):
        tasks = [
            asyncio.create_task(add(BENCH, revision.id, NewBomLine(part, Designators.parse("R1"))))
            for part in (resistor, capacitor)
        ]
        await until_waiting(engine, 2)
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    refused = [outcome for outcome in outcomes if isinstance(outcome, DesignatorTakenError)]
    assert len(refused) == 1
    assert refused[0].item == "R1"
    (line,) = await read_bom(engine, revision)
    assert refused[0].line_id == line.id
    assert await count(engine, "bom_designators") == 1


async def test_an_add_that_waited_while_the_revision_was_reserved_is_refused(
    engine: AsyncEngine,
) -> None:
    # Decision 12: the status is read after the lock, so a change made while this waited shows.
    revision = await stored_revision(engine)
    add, parts = adding(engine)
    resistor = parts.hold("4k7")
    reserve = RESERVE.bindparams(id=revision.id)

    async with project_held(engine, revision.project_id, then=reserve):
        task = asyncio.create_task(
            add(BENCH, revision.id, NewBomLine(resistor, Designators.parse("R1")))
        )
        await until_waiting(engine, 1)

    with pytest.raises(RevisionContentLockedError, match="reserved"):
        await task
    assert await count(engine, "bom_lines") == 0


async def test_an_edit_reads_the_revision_fresh_after_the_lock(engine: AsyncEngine) -> None:
    revision = await stored_revision(engine)
    line = a_line(revision, RESISTOR, "R1")
    await add_lines(engine, line)
    parts = FakePartLookup()
    parts.facts[RESISTOR] = facts_of(RESISTOR)
    edit = UpdateBomLine(factory(engine), parts, ManualClock(NOW))
    reserve = RESERVE.bindparams(id=revision.id)

    async with project_held(engine, revision.project_id, then=reserve):
        task = asyncio.create_task(
            edit(BENCH, revision.id, line.id, NewBomLine(RESISTOR, Designators.parse("R2")))
        )
        await until_waiting(engine, 1)

    with pytest.raises(RevisionContentLockedError):
        await task
    assert await read_bom(engine, revision) == (line,)


# --- A fork's copy -----------------------------------------------------------------------------


async def test_a_fork_copies_its_sources_lines_in_its_one_transaction(engine: AsyncEngine) -> None:
    source = await stored_revision(engine)
    held = (a_line(source, SENSOR, "U1"), a_line(source, RESISTOR, "R1-4", minutes=1))
    await add_lines(engine, *held)
    fork = ForkRevision(factory(engine), ManualClock(NOW + timedelta(hours=1)), NewIds())

    with committing(engine) as commits:
        made = await fork(BENCH, source.id, NewRevision())

    assert len(commits) == 1
    copies = await read_bom(engine, made)
    assert [line.content for line in copies] == [line.content for line in held]
    assert all(line.revision_id == made.id for line in copies)
    assert await read_bom(engine, source) == held


class CopyThenFailUnitOfWork(SqlProjectsUnitOfWork):
    """The real unit of work with a content that fails registered after the BOM's copy."""

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.revision_contents = (*self.revision_contents, FailingContent())
        return self


async def test_a_content_failing_after_the_copy_leaves_no_revision_and_no_line(
    engine: AsyncEngine,
) -> None:
    # Requirement 7.4: the copy was written, then the rollback took it and the fork.
    source = await stored_revision(engine)
    await add_lines(engine, a_line(source, RESISTOR, "R1-4"))
    sessions = create_session_factory(engine)
    ids = NewIds()
    fork = ForkRevision(
        lambda workspace_id: CopyThenFailUnitOfWork(sessions, workspace_id, ids),
        ManualClock(NOW),
        ids,
    )

    with pytest.raises(CopyFailedError):
        await fork(BENCH, source.id, NewRevision())

    assert await count(engine, "revisions") == 1
    assert (await count(engine, "bom_lines"), await count(engine, "bom_designators")) == (1, 4)


# --- SqlRevisions.project_of --------------------------------------------------------------------


async def test_project_of_answers_only_the_workspaces_own_revisions(engine: AsyncEngine) -> None:
    mine = await stored_revision(engine)
    theirs_project = a_project(workspace_id=OTHER)
    theirs = a_revision(theirs_project)
    await store(engine, theirs_project, theirs)

    async with projects_work(engine) as work:
        assert await work.revisions.project_of(mine.id) == mine.project_id
        assert await work.revisions.project_of(theirs.id) is None
        assert await work.revisions.project_of(RevisionId(uuid7())) is None


async def test_get_refreshes_a_revision_the_session_already_holds(engine: AsyncEngine) -> None:
    revision = await stored_revision(engine)

    async with projects_work(engine) as work:
        held = await work.revisions.get(revision.id)
        assert held is not None
        async with engine.begin() as other:
            await other.execute(
                update(revisions)
                .where(revisions.c.id == revision.id)
                .values(status=RevisionStatus.BUILT)
            )
        again = await work.revisions.get(revision.id)

    assert again is held
    assert held.status is RevisionStatus.BUILT
