"""Nets and their pin references against a real PostgreSQL (11-netlist-editor).

What only the database can answer: nets and references read back as written, in order and in
two statements; a net and its references written in two; an edit rewriting only what changed;
the keys, the CHECKs and the folded name index refusing what the domain would never write; the
cascades; and a fork copying the nets after the lines in its one transaction.
"""

from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import TextClause, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from support.bom import a_line
from support.identity import ManualClock, NewIds
from support.netlist import content_of
from support.projects import NOW
from support.sql import counting
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.projects.application.ports import NewRevision
from wiredex.projects.application.revisions import ForkRevision
from wiredex.projects.domain.netlist import Net, NetContent, WireColor
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import (
    NetId,
    PartId,
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    RevisionStatus,
    Tags,
    WorkspaceId,
)
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BENCH = WorkspaceId(uuid7())
OTHER = WorkspaceId(uuid7())
SENSOR = PartId(uuid7())


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


async def stored_revision(engine: AsyncEngine, workspace_id: WorkspaceId = BENCH) -> Revision:
    project = Project(
        id=ProjectId(uuid7()),
        workspace_id=workspace_id,
        name=ProjectName(f"Weather station {uuid7()}"),
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
    async with projects_work(engine, workspace_id) as work:
        await work.projects.add(project)
        await work.revisions.add(revision)
        await work.commit()
    return revision


def a_net(revision: Revision, content: NetContent, *, minutes: int = 0) -> Net:
    return Net.on(revision, NetId(uuid7()), content, NOW + timedelta(minutes=minutes))


async def add_nets(engine: AsyncEngine, *added: Net) -> None:
    async with projects_work(engine, added[0].workspace_id) as work:
        await work.nets.add_all(added)
        await work.commit()


async def read_nets(engine: AsyncEngine, revision: Revision) -> tuple[Net, ...]:
    async with projects_work(engine, revision.workspace_id) as work:
        return (await work.nets.of_revision(revision.id)).nets


async def count(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as connection:
        found = await connection.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
        return int(found or 0)


async def refused(engine: AsyncEngine, statement: TextClause, **values: object) -> None:
    """The statement, as the owner (no row-level security), refused by a key or a CHECK."""
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(statement, values)


async def test_nets_read_back_equal_in_order_and_in_two_statements(engine: AsyncEngine) -> None:
    revision = await stored_revision(engine)
    sda = a_net(revision, content_of("SDA", "U2.3", "U1.25", "R1.2", color=WireColor.BLUE))
    gnd = a_net(revision, content_of("GND", "U1.14", "U1.2", "U1.10"), minutes=1)

    async with projects_work(engine) as work:
        with counting(engine) as written:
            await work.nets.add_all((sda, gnd))
        await work.commit()
    async with projects_work(engine) as work:
        with counting(engine) as read:
            back = (await work.nets.of_revision(revision.id)).nets

    assert back == (sda, gnd)
    assert back[1].content.pins.text() == "U1.2, U1.10, U1.14"
    assert len(written) == 2, written
    assert len(read) == 2, read


async def test_an_edit_rewrites_the_references_only_when_they_changed(engine: AsyncEngine) -> None:
    revision = await stored_revision(engine)
    net = a_net(revision, content_of("SDA", "U1.25"))
    await add_nets(engine, net)

    recolored = net.revised(content_of("SDA", "U1.25", color=WireColor.YELLOW))
    async with projects_work(engine) as work:
        with counting(engine) as statements:
            await work.nets.update(net, recolored)
        await work.commit()
    rewired = recolored.revised(content_of("SDA", "U1.25", "R1.2"))
    async with projects_work(engine) as work:
        await work.nets.update(recolored, rewired)
        await work.commit()

    assert len(statements) == 1, statements
    assert await read_nets(engine, revision) == (rewired,)


async def test_a_net_is_removed_with_its_references(engine: AsyncEngine) -> None:
    revision = await stored_revision(engine)
    net = a_net(revision, content_of("SDA", "U1.25", "R1.2"))
    await add_nets(engine, net)

    async with projects_work(engine) as work:
        await work.nets.remove(net)
        await work.commit()

    assert await count(engine, "nets") == 0
    assert await count(engine, "net_pins") == 0


async def test_the_cascade_from_a_revision(engine: AsyncEngine) -> None:
    revision = await stored_revision(engine)
    await add_nets(engine, a_net(revision, content_of("SDA", "U1.25")))

    async with projects_work(engine) as work:
        await work.revisions.remove(revision)
        await work.commit()

    assert await count(engine, "net_pins") == 0


async def test_two_names_equal_ignoring_case_are_refused_by_the_index(engine: AsyncEngine) -> None:
    revision = await stored_revision(engine)
    await add_nets(engine, a_net(revision, content_of("SDA", "U1.25")))

    with pytest.raises(IntegrityError):
        await add_nets(engine, a_net(revision, content_of("sda", "U2.3")))


async def test_the_database_refuses_what_the_domain_never_writes(engine: AsyncEngine) -> None:
    revision = await stored_revision(engine)
    net = a_net(revision, content_of("SDA", "U1.25"))
    await add_nets(engine, net)
    elsewhere = await stored_revision(engine, OTHER)
    row = text(
        "INSERT INTO net_pins (workspace_id, revision_id, net_id, designator, pin) "
        "VALUES (:workspace, :revision, :net, :designator, :pin)"
    )
    same = {"workspace": BENCH, "revision": revision.id, "net": net.id}

    await refused(engine, row, **same, designator="u1", pin="1")
    await refused(engine, row, **same, designator="U1", pin="a1")
    await refused(engine, row, **same, designator="U1", pin="25")  # the key: once per net
    await refused(
        engine, row, workspace=OTHER, revision=elsewhere.id, net=net.id, designator="U1", pin="1"
    )
    await refused(
        engine,
        text(
            "INSERT INTO nets (id, workspace_id, revision_id, name, color, created_at) "
            "VALUES (:id, :workspace, :revision, 'X', 'pink', now())"
        ),
        id=uuid7(),
        workspace=BENCH,
        revision=revision.id,
    )


async def test_a_fork_copies_the_nets_after_the_lines_in_one_transaction(
    engine: AsyncEngine,
) -> None:
    source = await stored_revision(engine)
    async with projects_work(engine) as work:
        await work.bom_lines.add(a_line(source, SENSOR, "U2"))
        await work.commit()
    await add_nets(
        engine,
        a_net(source, content_of("SDA", "U2.3", "R1.2", color=WireColor.BLUE)),
        a_net(source, content_of("SCL", "U2.4"), minutes=1),
    )
    sessions = create_session_factory(engine)
    ids = NewIds()
    fork_revision = ForkRevision(
        lambda workspace_id: SqlProjectsUnitOfWork(sessions, workspace_id, ids),
        ManualClock(NOW + timedelta(hours=1)),
        ids,
    )

    fork = await fork_revision(BENCH, source.id, NewRevision())

    copied = await read_nets(engine, fork)
    original = await read_nets(engine, source)
    assert [net.content for net in copied] == [net.content for net in original]
    assert {net.id for net in copied}.isdisjoint({net.id for net in original})
