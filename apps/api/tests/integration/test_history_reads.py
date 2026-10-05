"""History read back over Postgres, as `wiredex_app` (17-history, task 3).

What only the database can show: a page of the feed and of a timeline in three statements
whatever its size, walked page by page without a change seen twice or missed; a project's
timeline holding what its revisions hold; a change's first 20 rows, its own row first, and the
count of the rest; long values shortened on the way out; another bench's changes unseen and
uncounted; and a timeline of a record in the trash a 404, through the modules' own reads.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
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
from wiredex.bootstrap.trash import trash_use_cases
from wiredex.catalog.domain.values import PartDefinitionId
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.history.api.router import HistoryUseCases
from wiredex.history.domain.errors import RecordNotFoundError
from wiredex.history.domain.history import (
    MAX_ROWS_SHOWN,
    Action,
    ActivityFilter,
    Change,
    RecordKind,
    RowKind,
)
from wiredex.history.domain.values import WorkspaceId
from wiredex.history.infrastructure.unit_of_work import SqlHistoryUnitOfWork
from wiredex.shared_kernel.domain.paging import Page, PageRequest

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
        trash_use_cases(sessions),
    )
    return history_use_cases(sessions, modules)


def history_of(app: AsyncEngine, bench: Bench) -> SqlHistoryUnitOfWork:
    return SqlHistoryUnitOfWork(create_session_factory(app), WorkspaceId(bench.workspace))


async def test_a_page_costs_three_statements_whatever_its_size(app: AsyncEngine) -> None:
    # Requirement 8.3, for the feed and a timeline alike: the count, the changes, their rows.
    bench = a_bench()
    await write(app, bench, *BENCH)
    project = (RecordKind.PROJECT, bench["project"])
    async with history_of(app, bench) as work:
        with counting(app) as few:
            await work.changes.count()
            small = await work.changes.page(PageRequest())
    for _ in range(4):
        await write(app, bench, "UPDATE projects SET name = name || ' 2' WHERE id = :project")
    async with history_of(app, bench) as work:
        with counting(app) as many:
            await work.changes.count()
            large = await work.changes.page(PageRequest())
        with counting(app) as timeline:
            await work.changes.count(project)
            projects = await work.changes.page(PageRequest(), project)

    assert (len(small), len(large), len(projects)) == (6, 10, 5)
    assert len(few) == len(many) == len(timeline) == 3


async def walk(
    read: Callable[[PageRequest], Awaitable[Page[Change]]], size: int
) -> list[Page[Change]]:
    """Every page of a list, from the first to the last the total gives."""
    pages = [await read(PageRequest(1, size))]
    while pages[-1].request.number * size < pages[-1].total:
        pages.append(await read(PageRequest(pages[-1].request.number + 1, size)))
    return pages


async def test_walking_the_pages_sees_each_change_once_newest_first(
    app: AsyncEngine, history: HistoryUseCases, migrated_database_url: str
) -> None:
    # Fifteen changes, six of them written in one transaction and four in another.
    mine, theirs = a_bench(), a_bench()
    await write(app, mine, *BENCH)
    await write(app, theirs, *BENCH)
    for _ in range(5):
        await write(app, mine, "UPDATE projects SET name = name || ' 2' WHERE id = :project")
    await write(
        app,
        mine,
        "UPDATE part_definitions SET name = 'BME280 board' WHERE id = :part",
        "UPDATE firmware SET name = 'Station' WHERE id = :firmware",
        "UPDATE locations SET name = 'Drawer 2' WHERE id = :location",
        "UPDATE units SET serial = 'S-1' WHERE id = :unit",
    )
    # `occurred_at` is each change's own clock reading; set by the owner to one instant, every
    # change ties on it, and only the id can order the pages.
    owner = create_async_engine(migrated_database_url)
    async with owner.begin() as connection:
        await connection.execute(
            text("UPDATE history_changes SET occurred_at = now() WHERE workspace_id = :w"),
            {"w": mine.workspace},
        )
    await owner.dispose()
    here = WorkspaceId(mine.workspace)
    project = (RecordKind.PROJECT, mine["project"])
    projects_only = ActivityFilter(kind=RecordKind.PROJECT)

    async with history_of(app, mine) as work:
        every = await work.changes.page(PageRequest(1, 100))
    feed = await walk(lambda page: history.list_activity(here, page), 4)
    narrowed = await walk(lambda page: history.list_activity(here, page, projects_only), 4)
    timeline = await walk(lambda page: history.list_timeline(here, project, page), 4)

    ids = [change.id for change in every]
    assert len(ids) == 15
    assert ids == sorted(ids, reverse=True)
    assert len({change.occurred_at for change in every}) == 1
    for pages, expected in (
        (feed, ids),
        (narrowed, [change.id for change in every if projects_only.matches(change)]),
        (timeline, [change.id for change in every if change.record.id == mine["project"]]),
    ):
        seen = [change.id for page in pages for change in page.items]
        assert seen == expected
        assert {page.total for page in pages} == {len(expected)}
        assert [page.request.number for page in pages] == list(range(1, len(pages) + 1))
    assert [len(page.items) for page in feed] == [4, 4, 4, 3]
    assert [len(page.items) for page in narrowed] == [4, 2]
    # Their bench wrote six changes too; none of them is counted here.
    assert {change.record.id for change in every}.isdisjoint(set(theirs.ids.values()))


async def test_a_page_past_the_end_is_the_last_page(
    app: AsyncEngine, history: HistoryUseCases
) -> None:
    bench = a_bench()
    await write(app, bench, *BENCH)

    last = await history.list_activity(WorkspaceId(bench.workspace), PageRequest(40, 4))

    assert (last.request, last.total, len(last.items)) == (PageRequest(2, 4), 6, 2)


async def test_a_projects_timeline_holds_what_its_revisions_hold(app: AsyncEngine) -> None:
    bench = a_bench()
    await write(app, bench, *BENCH)
    await write(app, bench, "UPDATE nets SET color = 'red' WHERE id = :net")

    async with history_of(app, bench) as work:
        changes = await work.changes.page(PageRequest(), (RecordKind.PROJECT, bench["project"]))

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
        [saved, *_] = await work.changes.page(PageRequest(1, 1), (RecordKind.PART, bench["part"]))

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
        [edited, *_] = await work.changes.page(PageRequest(1, 1))

    fields = {field.name: field for field in edited.rows[0].fields()}
    assert fields["content"].after == "x" * 300 + "…"
    assert fields["size"].after == "400"


async def test_another_benchs_changes_are_unseen(app: AsyncEngine) -> None:
    # Requirement 6.1, as wiredex_app: its policies, and the repository's own filter.
    mine, theirs = a_bench(), a_bench()
    await write(app, mine, *BENCH)
    await write(app, theirs, *BENCH)

    async with history_of(app, mine) as work:
        seen = await work.changes.page(PageRequest(1, 100))
        counted = await work.changes.count()
        their_part = await work.changes.page(PageRequest(1, 100), (RecordKind.PART, theirs["part"]))
        their_part_counted = await work.changes.count((RecordKind.PART, theirs["part"]))

    assert {change.record.id for change in seen}.isdisjoint(set(theirs.ids.values()))
    assert len(seen) == counted == 6
    assert their_part == []
    assert their_part_counted == 0


async def test_the_feeds_filters_select_what_the_domain_matches(app: AsyncEngine) -> None:
    # Every action a change can have, written as the modules would, then each filter asked of
    # the database: it selects the changes `ActivityFilter.matches` keeps, in the same order.
    bench = a_bench()
    await write(app, bench, *BENCH)
    await write(app, bench, "UPDATE part_definitions SET name = 'BME280 board' WHERE id = :part")
    await write(app, bench, "UPDATE projects SET trashed_at = now() WHERE id = :project")
    await write(app, bench, "UPDATE projects SET trashed_at = NULL WHERE id = :project")
    await write(
        app, bench, "UPDATE firmware SET name = 'Station' WHERE id = :firmware", reason="restore"
    )
    # A change to what a project holds, with no row of the project itself: an edit.
    await write(app, bench, "UPDATE nets SET color = 'red' WHERE id = :net")
    spare = (
        "INSERT INTO locations (id, workspace_id, parent_id, code, name, created_at)"
        " VALUES (gen_random_uuid(), :w, NULL, 'WX-L-9002', 'Spare 100%', now())"
    )
    await write(app, bench, spare)
    await write(app, bench, "DELETE FROM locations WHERE code = 'WX-L-9002' AND workspace_id = :w")
    filters = [
        *(ActivityFilter(action=action) for action in Action),
        ActivityFilter(kind=RecordKind.PROJECT),
        ActivityFilter(text="  STATION "),
        ActivityFilter(text="100%"),
        ActivityFilter(text="s%"),
        ActivityFilter(kind=RecordKind.PROJECT, action=Action.EDITED, text="weather"),
    ]

    async with history_of(app, bench) as work:
        every = await work.changes.page(PageRequest(1, 100))
        selected = [
            await work.changes.page(PageRequest(1, 100), narrowing=wanted) for wanted in filters
        ]
        counted = [await work.changes.count(narrowing=wanted) for wanted in filters]
        with counting(app) as statements:
            await work.changes.page(PageRequest(1, 100), narrowing=filters[0])

    assert {change.action for change in every} == set(Action)
    for wanted, found in zip(filters, selected, strict=True):
        expected = [change.id for change in every if wanted.matches(change)]
        assert [change.id for change in found] == expected, wanted
    # The count is narrowed by the same filters, the action's lateral join included.
    assert counted == [len(found) for found in selected]
    # `%` is a character, not "any run": "100%" is the spare's label alone, its two changes,
    # and "s%" is in no label, where a wildcard would have matched every name holding an s.
    assert [len(found) for found in selected[-3:-1]] == [2, 0]
    assert len(statements) == 2


async def test_a_timeline_answers_404_where_the_records_page_does(
    app: AsyncEngine, history: HistoryUseCases
) -> None:
    # Requirement 3.2: asked of the modules' own reads, so a part in the trash is absent.
    bench = a_bench()
    await write(app, bench, *BENCH)
    here = WorkspaceId(bench.workspace)
    part = (RecordKind.PART, bench["part"])

    page = await history.list_timeline(here, part, PageRequest())
    assert [change.record.id for change in page.items] == [bench["part"]]

    # Off the BOM first, so the part's own route takes it to the trash.
    await write(app, bench, "DELETE FROM bom_lines WHERE id = :line")
    catalog = catalog_use_cases(create_session_factory(app))
    await catalog.delete_part(CatalogWorkspaceId(bench.workspace), PartDefinitionId(bench["part"]))

    with pytest.raises(RecordNotFoundError):
        await history.list_timeline(here, part, PageRequest())
    with pytest.raises(RecordNotFoundError):
        await history.list_timeline(WorkspaceId(uuid7()), part, PageRequest())
    # The project's second change is the BOM line taken off above.
    for kind, name, changes in (
        (RecordKind.UNIT, "unit", 1),
        (RecordKind.PROJECT, "project", 2),
        (RecordKind.FIRMWARE, "firmware", 1),
    ):
        found = await history.list_timeline(here, (kind, bench[name]), PageRequest())
        assert (len(found.items), found.total) == (changes, changes)
