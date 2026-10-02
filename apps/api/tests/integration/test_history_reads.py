"""History read back over Postgres, as `wiredex_app` (17-history, task 3).

What only the database can show: a page of the feed and of a timeline in two statements whatever
its size; a project's timeline holding what its revisions hold; a change's first 20 rows, its own
row first, and the count of the rest; long values shortened on the way out; another bench's
changes unseen; and a timeline of a record in the trash a 404, through the modules' own reads.
"""

from collections.abc import AsyncIterator
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from support.history_bench import BENCH, Bench, a_bench, write
from support.sql import counting
from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.firmware import firmware_use_cases
from wiredex.bootstrap.history import HistoryModules, history_use_cases
from wiredex.bootstrap.inventory import inventory_use_cases
from wiredex.bootstrap.projects import projects_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.domain.values import PartDefinitionId
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.history.api.router import HistoryUseCases
from wiredex.history.domain.errors import RecordNotFoundError
from wiredex.history.domain.history import MAX_ROWS_SHOWN, RecordKind, RowKind
from wiredex.history.domain.values import WorkspaceId
from wiredex.history.infrastructure.unit_of_work import SqlHistoryUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

TABLES = (
    "history_entries, history_changes, flashes, firmware_revisions, source_files,"
    " firmware_versions, firmware, net_pins, nets, bom_designators, bom_lines, revisions,"
    " projects, units, stock_lots, locations, attachments, files, pins, part_definitions,"
    " attribute_definitions, categories"
)


@pytest.fixture(autouse=True)
async def clean(migrated_database_url: str) -> AsyncIterator[None]:
    """Emptied by the owner afterwards: the app role is granted no TRUNCATE."""
    yield
    engine = create_async_engine(migrated_database_url)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    await engine.dispose()


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


@pytest.fixture
def history(app: AsyncEngine) -> HistoryUseCases:
    sessions = create_session_factory(app)
    modules = HistoryModules(
        catalog_use_cases(sessions),
        inventory_use_cases(sessions),
        projects_use_cases(sessions),
        firmware_use_cases(sessions),
    )
    return history_use_cases(sessions, modules)


def history_of(app: AsyncEngine, bench: Bench) -> SqlHistoryUnitOfWork:
    return SqlHistoryUnitOfWork(create_session_factory(app), WorkspaceId(bench.workspace))


async def test_a_page_costs_two_statements_whatever_its_size(app: AsyncEngine) -> None:
    # Requirement 8.3, for the feed and a timeline alike.
    bench = a_bench()
    await write(app, bench, *BENCH)
    async with history_of(app, bench) as work:
        with counting(app) as few:
            small = await work.changes.page(None, 50)
    for _ in range(4):
        await write(app, bench, "UPDATE projects SET name = name || ' 2' WHERE id = :project")
    async with history_of(app, bench) as work:
        with counting(app) as many:
            large = await work.changes.page(None, 50)
        with counting(app) as timeline:
            projects = await work.changes.page(None, 50, (RecordKind.PROJECT, bench["project"]))

    assert (len(small), len(large), len(projects)) == (6, 10, 5)
    assert len(few) == len(many) == len(timeline) == 2


async def test_a_projects_timeline_holds_what_its_revisions_hold(app: AsyncEngine) -> None:
    bench = a_bench()
    await write(app, bench, *BENCH)
    await write(app, bench, "UPDATE nets SET color = 'red' WHERE id = :net")

    async with history_of(app, bench) as work:
        changes = await work.changes.page(None, 50, (RecordKind.PROJECT, bench["project"]))

    recolored, created = changes
    [net] = recolored.rows
    assert (net.kind, net.label, [field.name for field in net.fields()]) == (
        RowKind.NET,
        "SDA",
        ["color"],
    )
    assert [row.kind for row in created.rows] == [
        RowKind.PROJECT,
        RowKind.REVISION,
        RowKind.BOM_LINE,
        RowKind.DESIGNATOR,
        RowKind.NET,
        RowKind.NET_PIN,
    ]
    assert created.rows[0].own


async def test_a_change_shows_its_first_rows_its_own_first_and_counts_the_rest(
    app: AsyncEngine,
) -> None:
    # Requirement 2.3: a pinout of 25 pins saved with the part renamed.
    bench = a_bench()
    await write(app, bench, *BENCH)
    pins = (
        "INSERT INTO pins (workspace_id, part_id, number, position, label, type, functions)"
        " SELECT :w, :part, n::text, n, 'P' || n, 'io', '{}' FROM generate_series(10, 34) AS n"
    )
    await write(app, bench, pins, "UPDATE part_definitions SET name = 'BME280' WHERE id = :part")

    async with history_of(app, bench) as work:
        [saved, *_] = await work.changes.page(None, 1, (RecordKind.PART, bench["part"]))

    assert saved.row_count == 26
    assert len(saved.rows) == MAX_ROWS_SHOWN
    assert saved.more_rows == 6
    assert saved.rows[0].own
    assert saved.rows[0].kind is RowKind.PART


async def test_long_values_are_shortened_on_the_way_out(app: AsyncEngine) -> None:
    bench = a_bench()
    await write(app, bench, *BENCH)
    await write(
        app,
        bench,
        "UPDATE source_files SET content = repeat('x', 400), size = 400 WHERE id = :file",
    )

    async with history_of(app, bench) as work:
        [edited, *_] = await work.changes.page(None, 1)

    fields = {field.name: field for field in edited.rows[0].fields()}
    assert fields["content"].after == "x" * 300 + "…"
    assert fields["size"].after == "400"


async def test_another_benchs_changes_are_unseen(app: AsyncEngine) -> None:
    # Requirement 6.1, as wiredex_app: its policies, and the repository's own filter.
    mine, theirs = a_bench(), a_bench()
    await write(app, mine, *BENCH)
    await write(app, theirs, *BENCH)

    async with history_of(app, mine) as work:
        seen = await work.changes.page(None, 100)
        their_part = await work.changes.page(None, 100, (RecordKind.PART, theirs["part"]))

    assert {change.record.id for change in seen}.isdisjoint(set(theirs.ids.values()))
    assert len(seen) == 6
    assert their_part == []


async def test_a_timeline_answers_404_where_the_records_page_does(
    app: AsyncEngine, history: HistoryUseCases
) -> None:
    # Requirement 3.2: asked of the modules' own reads, so a part in the trash is absent.
    bench = a_bench()
    await write(app, bench, *BENCH)
    here = WorkspaceId(bench.workspace)
    part = (RecordKind.PART, bench["part"])

    page = await history.list_timeline(here, part, None, 50)
    assert [change.record.id for change in page.changes] == [bench["part"]]

    # Off the BOM first, so the part's own route takes it to the trash.
    await write(app, bench, "DELETE FROM bom_lines WHERE id = :line")
    catalog = catalog_use_cases(create_session_factory(app))
    await catalog.delete_part(CatalogWorkspaceId(bench.workspace), PartDefinitionId(bench["part"]))

    with pytest.raises(RecordNotFoundError):
        await history.list_timeline(here, part, None, 50)
    with pytest.raises(RecordNotFoundError):
        await history.list_timeline(WorkspaceId(uuid7()), part, None, 50)
    # The project's second change is the BOM line taken off above.
    for kind, name, changes in (
        (RecordKind.UNIT, "unit", 1),
        (RecordKind.PROJECT, "project", 2),
        (RecordKind.FIRMWARE, "firmware", 1),
    ):
        found = await history.list_timeline(here, (kind, bench[name]), None, 50)
        assert len(found.changes) == changes
