"""Minimum stock and the reorder list (24-minimum-stock): a part's own minimum, a category's
default inherited down the tree, and the parts below theirs, compared by what the workspace
chose: what is free, or everything on hand.
"""

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from support.catalog import BENCH, World
from wiredex.catalog.api.router import create_router
from wiredex.catalog.application.parts import NewPart, PartRevision
from wiredex.catalog.domain.category import CategoryFlags, resolve_flags_of
from wiredex.catalog.domain.errors import InvalidMinimumStockError
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.reorder import StockBasis
from wiredex.catalog.domain.values import PartName, WorkspaceId, checked_minimum

CATALOG = "/api/catalog"


async def the_bench(_request: Request) -> WorkspaceId:
    return BENCH


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def client(world: World) -> TestClient:
    app = FastAPI()
    app.include_router(create_router(world.catalog_use_cases(), the_bench), prefix="/api")
    return TestClient(app)


def watch(world: World, part: PartDefinition, minimum: int | None, held: int = 0) -> None:
    part.minimum_stock = minimum
    if held:
        world.part_stock.held[part.id] = held


# --- The value ------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, 0, 1, 20, 1_000_000])
def test_a_minimum_is_none_or_a_whole_number_up_to_a_million(value: int | None) -> None:
    assert checked_minimum(value) == value


@pytest.mark.parametrize("value", [-1, 1_000_001, True])
def test_anything_else_is_refused(value: int) -> None:
    with pytest.raises(InvalidMinimumStockError):
        checked_minimum(value)
    with pytest.raises(InvalidMinimumStockError):
        PartDetails(PartName("R 4k7"), minimum_stock=value)


# --- A category's default -------------------------------------------------------------


def test_nothing_set_anywhere_is_no_minimum() -> None:
    world = World()

    assert resolve_flags_of([world.passives, world.resistors]) == CategoryFlags()
    assert CategoryFlags().minimum_stock is None


def test_the_nearest_minimum_set_wins_and_zero_is_an_answer() -> None:
    world = World()
    world.passives.minimum_stock = 20

    assert resolve_flags_of([world.passives, world.resistors]).minimum_stock == 20
    world.resistors.minimum_stock = 0
    assert resolve_flags_of([world.passives, world.resistors]).minimum_stock == 0
    world.resistors.minimum_stock = 50
    assert resolve_flags_of([world.passives, world.resistors]).minimum_stock == 50


@pytest.mark.anyio
async def test_setting_a_categorys_minimum_commits_once_and_clearing_inherits_again() -> None:
    world = World()
    await world.set_category_minimum(BENCH, world.passives.id, 20)
    commits = world.catalog.commits

    own = await world.set_category_minimum(BENCH, world.resistors.id, 5)
    again = await world.set_category_minimum(BENCH, world.resistors.id, 5)

    assert (own.category.minimum_stock, own.flags.minimum_stock) == (5, 5)
    assert again.flags.minimum_stock == 5
    assert world.catalog.commits == commits + 1
    cleared = await world.set_category_minimum(BENCH, world.resistors.id, None)
    assert (cleared.category.minimum_stock, cleared.flags.minimum_stock) == (None, 20)


def test_a_category_patch_sets_clears_and_leaves_the_minimum(
    client: TestClient, world: World
) -> None:
    def patched(**body: Any) -> dict[str, Any]:
        response = client.patch(f"{CATALOG}/categories/{world.resistors.id}", json=body)
        assert response.status_code == 200, response.text
        answered: dict[str, Any] = response.json()
        return answered

    client.patch(f"{CATALOG}/categories/{world.passives.id}", json={"minimum_stock": 20})

    inherits = patched(name="Resistors")
    assert (inherits["minimum_stock"], inherits["minimum_stock_resolved"]) == (None, 20)
    own = patched(minimum_stock=0)
    assert (own["minimum_stock"], own["minimum_stock_resolved"]) == (0, 0)
    # A patch that doesn't mention it leaves it alone; null clears it.
    assert patched(name="Resistors")["minimum_stock"] == 0
    assert patched(minimum_stock=None)["minimum_stock_resolved"] == 20
    refused = client.patch(f"{CATALOG}/categories/{world.resistors.id}", json={"minimum_stock": -1})
    assert refused.status_code == 422


# --- A part's minimum -----------------------------------------------------------------


@pytest.mark.anyio
async def test_a_part_keeps_its_own_minimum_and_an_edit_replaces_it() -> None:
    world = World()
    details = PartDetails(PartName("R 4k7"), minimum_stock=30)

    part = await world.define_part(
        BENCH, NewPart(world.resistors.id, details, {"resistance": "4k7"})
    )
    assert part.minimum_stock == 30

    commits = world.catalog.commits
    cleared = PartRevision(PartDetails(PartName("R 4k7")), {"resistance": "4k7"})
    view = await world.update_part(BENCH, part.id, cleared)
    assert view.part.minimum_stock is None
    assert view.minimum is None
    assert world.catalog.commits == commits + 1


@pytest.mark.anyio
async def test_a_part_page_says_the_minimum_it_is_held_to_and_where_it_comes_from() -> None:
    world = World()
    world.passives.minimum_stock = 20
    part = world.add_part(world.resistors)

    inherited = (await world.get_part(BENCH, part.id)).minimum
    assert inherited is not None
    assert (inherited.quantity, inherited.inherited_from) == (20, world.passives)

    part.minimum_stock = 5
    own = (await world.get_part(BENCH, part.id)).minimum
    assert own is not None
    assert (own.quantity, own.inherited_from) == (5, None)

    part.minimum_stock = 0
    assert (await world.get_part(BENCH, part.id)).minimum is None


@pytest.mark.anyio
async def test_a_part_of_a_category_that_isnt_stocked_is_never_watched() -> None:
    world = World()
    world.passives.minimum_stock = 20
    world.resistors.not_stocked = True
    part = world.add_part(world.resistors)
    part.minimum_stock = 5

    assert (await world.get_part(BENCH, part.id)).minimum is None
    assert (await world.list_reorder(BENCH)).lines == []


def test_a_part_answers_its_minimum_on_the_wire(client: TestClient, world: World) -> None:
    world.passives.minimum_stock = 20
    created = client.post(
        f"{CATALOG}/parts",
        json={
            "category_id": str(world.resistors.id),
            "name": "R 4k7",
            "attributes": {"resistance": "4k7"},
        },
    )
    assert created.status_code == 201, created.text
    part = client.get(f"{CATALOG}/parts/{created.json()['id']}").json()
    assert part["minimum_stock"] is None
    assert part["minimum_stock_resolved"] == 20
    assert part["minimum_stock_from"] == {"id": str(world.passives.id), "name": "Passives"}

    edited = client.patch(
        f"{CATALOG}/parts/{part['id']}",
        json={"name": "R 4k7", "attributes": {"resistance": "4k7"}, "minimum_stock": 3},
    ).json()
    assert (edited["minimum_stock"], edited["minimum_stock_resolved"]) == (3, 3)
    assert edited["minimum_stock_from"] is None
    too_many = client.patch(
        f"{CATALOG}/parts/{part['id']}",
        json={"name": "R 4k7", "attributes": {"resistance": "4k7"}, "minimum_stock": 1_000_001},
    )
    assert too_many.status_code == 422


# --- The list -------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_list_holds_the_parts_below_their_minimum_the_emptiest_first() -> None:
    world = World()
    plenty = world.add_part(world.resistors, "R plenty")
    low = world.add_part(world.resistors, "R low")
    empty = world.add_part(world.resistors, "R empty")
    at_minimum = world.add_part(world.resistors, "R exact")
    unwatched = world.add_part(world.resistors, "R unwatched")
    watch(world, plenty, 20, held=35)
    watch(world, low, 20, held=15)
    watch(world, empty, 2)
    watch(world, at_minimum, 10, held=10)
    watch(world, unwatched, None, held=0)

    view = await world.list_reorder(BENCH)

    assert [(line.part.name.value, line.have, line.missing) for line in view.lines] == [
        ("R empty", 0, 2),
        ("R low", 15, 5),
    ]
    assert view.basis is StockBasis.FREE


@pytest.mark.anyio
async def test_what_is_reserved_counts_only_when_the_workspace_compares_by_total() -> None:
    world = World()
    insert = world.add_part(world.resistors, "M3 insert")
    watch(world, insert, 50, held=60)
    world.part_stock.reserved[insert.id] = 20

    free = await world.list_reorder(BENCH)
    assert [(line.have, line.missing) for line in free.lines] == [(40, 10)]

    world.stock_basis = StockBasis.TOTAL
    total = await world.list_reorder(BENCH)
    assert total.lines == []
    assert total.basis is StockBasis.TOTAL
    assert [basis for _, basis in world.part_stock.asked_levels] == [
        StockBasis.FREE,
        StockBasis.TOTAL,
    ]


@pytest.mark.anyio
async def test_a_categorys_default_watches_its_parts_and_a_parts_own_answer_overrides() -> None:
    world = World()
    world.passives.minimum_stock = 10
    inherits = world.add_part(world.resistors, "R inherits")
    own = world.add_part(world.resistors, "R own")
    opted_out = world.add_part(world.resistors, "R opted out")
    watch(world, inherits, None, held=4)
    watch(world, own, 100, held=40)
    watch(world, opted_out, 0)

    lines = (await world.list_reorder(BENCH)).lines

    assert [(line.part.name.value, line.minimum.quantity) for line in lines] == [
        ("R inherits", 10),
        ("R own", 100),
    ]
    assert lines[0].minimum.inherited_from is world.passives
    assert lines[0].category is world.resistors
    assert lines[1].minimum.inherited_from is None


@pytest.mark.anyio
async def test_a_part_in_the_trash_isnt_listed() -> None:
    world = World()
    gone = world.add_part(world.resistors, "R gone")
    watch(world, gone, 5)
    gone.move_to_trash(world.clock.now())

    assert (await world.list_reorder(BENCH)).lines == []


def test_the_list_on_the_wire(client: TestClient, world: World) -> None:
    world.passives.minimum_stock = 10
    low = world.add_part(world.resistors, "R low")
    world.part_stock.held[low.id] = 4

    answered = client.get(f"{CATALOG}/reorder")

    assert answered.status_code == 200, answered.text
    assert answered.json() == {
        "basis": "free",
        "items": [
            {
                "part_id": str(low.id),
                "name": "R low",
                "mpn": None,
                "category": {"id": str(world.resistors.id), "name": "Resistors"},
                "minimum": 10,
                "minimum_from": {"id": str(world.passives.id), "name": "Passives"},
                "have": 4,
                "missing": 6,
            }
        ],
    }
