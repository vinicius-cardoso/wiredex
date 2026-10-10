"""A category's kind, mechanical or electronic (21-part-kinds): the third inherited flag, set
and resolved as *tracked individually* and *not stocked* are, and what the catalog refuses of a
mechanical part.
"""

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from support.catalog import BENCH, World
from wiredex.catalog.api.router import create_router
from wiredex.catalog.domain.category import Category, CategoryFlags, resolve_flags_of
from wiredex.catalog.domain.values import WorkspaceId

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


def patched(client: TestClient, category: Category, **body: Any) -> dict[str, Any]:
    response = client.patch(f"{CATALOG}/categories/{category.id}", json=body)
    assert response.status_code == 200, response.text
    answered: dict[str, Any] = response.json()
    return answered


# --- The flag -------------------------------------------------------------------------


def test_nothing_set_anywhere_is_electronic() -> None:
    # What every part was before the flag existed, so no stored category needs a value.
    world = World()
    assert resolve_flags_of([world.passives, world.resistors]) == CategoryFlags()
    assert CategoryFlags().mechanical is False


def test_the_nearest_set_kind_wins_apart_from_the_other_flags() -> None:
    world = World()
    hardware = world.add_category("Hardware")
    bolts = world.add_category("Bolts", hardware)
    sensors = world.add_category("Sensor mounts", hardware)
    hardware.mechanical = True
    hardware.tracked_individually = True
    sensors.mechanical = False

    assert resolve_flags_of([hardware, bolts]) == CategoryFlags(
        tracked_individually=True, mechanical=True
    )
    assert resolve_flags_of([hardware, sensors]).mechanical is False


def test_setting_the_kind_reports_a_change_only_when_there_is_one() -> None:
    world = World()
    assert world.passives.set_mechanical(True)
    assert not world.passives.set_mechanical(True)
    assert world.passives.set_mechanical(None)
    assert world.passives.mechanical is None


@pytest.mark.anyio
async def test_a_kind_is_stored_inherited_and_a_no_op_commits_nothing() -> None:
    # Requirements 1.1 and 1.5.
    world = World()

    view = await world.set_category_kind(BENCH, world.passives.id, True)
    assert (view.category.mechanical, view.flags.mechanical) == (True, True)
    assert world.catalog.commits == 1

    again = await world.set_category_kind(BENCH, world.passives.id, True)
    assert again.flags.mechanical is True
    assert world.catalog.commits == 1

    # Resistors sets nothing, so it answers as Passives does, until it answers for itself.
    schema = await world.get_category_schema(BENCH, world.resistors.id)
    assert schema.flags.mechanical is True
    own = await world.set_category_kind(BENCH, world.resistors.id, False)
    assert (own.category.mechanical, own.flags.mechanical) == (False, False)


# --- The wire -------------------------------------------------------------------------


@pytest.mark.parametrize("value", [True, False, None])
def test_patching_the_kind_sets_it_and_resolves_it(
    client: TestClient, world: World, value: bool | None
) -> None:
    world.passives.mechanical = not value

    body = patched(client, world.passives, mechanical=value)

    assert (body["mechanical"], body["mechanical_resolved"]) == (value, value is True)
    # The other two flags are left as they were.
    assert (body["tracked_individually"], body["not_stocked"]) == (None, None)


def test_a_patch_leaving_the_kind_out_leaves_it_alone(client: TestClient, world: World) -> None:
    world.resistors.mechanical = True
    body = patched(client, world.resistors, name="Resistor networks")
    assert body["mechanical"] is True


def test_the_tree_a_schema_and_a_part_say_the_kind_they_resolve_to(
    client: TestClient, world: World
) -> None:
    # Requirement 1.2.
    part = world.add_part(world.resistors, "Standoff M3")
    patched(client, world.passives, mechanical=True)

    tree = {node["name"]: node for node in client.get(f"{CATALOG}/categories").json()}
    assert tree["Resistors"]["mechanical"] is None
    assert tree["Resistors"]["mechanical_resolved"] is True
    schema = client.get(f"{CATALOG}/categories/{world.resistors.id}/schema").json()
    assert schema["category"]["mechanical_resolved"] is True
    assert client.get(f"{CATALOG}/parts/{part.id}").json()["mechanical"] is True
