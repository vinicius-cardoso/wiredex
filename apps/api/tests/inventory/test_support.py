"""The inventory fakes stand up: the seeded world builds and the Parts port answers both kinds.

The repositories and use-case behaviour are exercised by the use-case tests that consume this
support module; here we only prove the seed is coherent, so those tests start from solid
ground.
"""

from uuid import uuid7

import pytest

from support.inventory import (
    LOT_COUNTED_PART,
    UNIT_TRACKED_PART,
    FakeParts,
    World,
)
from wiredex.inventory.application.ports import PartStockInfo
from wiredex.inventory.domain.values import PartId, WorkspaceId

pytestmark = pytest.mark.anyio


def test_world_seeds_lab_with_a_drawer_under_it() -> None:
    world = World()

    assert world.lab.parent_id is None
    assert world.drawer.parent_id == world.lab.id
    assert str(world.lab.code) == "WX-L-0001"
    assert str(world.drawer.code) == "WX-L-0002"
    assert set(world.inventory.locations.saved) == {world.lab.id, world.drawer.id}


async def test_fake_parts_answers_both_kinds() -> None:
    parts = FakeParts()
    workspace = WorkspaceId(uuid7())

    lot_counted = await parts.describe(workspace, LOT_COUNTED_PART)
    unit_tracked = await parts.describe(workspace, UNIT_TRACKED_PART)
    absent = await parts.describe(workspace, PartId(uuid7()))

    assert lot_counted == PartStockInfo(exists=True, tracked_individually=False)
    assert unit_tracked == PartStockInfo(exists=True, tracked_individually=True)
    assert absent == PartStockInfo(exists=False, tracked_individually=False)
