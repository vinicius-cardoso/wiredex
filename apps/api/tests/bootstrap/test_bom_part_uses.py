"""`BomPartUses` over the in-memory projects: which BOMs name a part, in catalog's words.

The adapter drives a real `ListPartUses` over the projects fakes, as the composition root
drives it over Postgres.
"""

from uuid import uuid7

import pytest

from support.bom import a_line
from support.projects import BENCH, World
from wiredex.bootstrap.catalog import BomPartUses
from wiredex.catalog.domain.usage import PartUsage, PartUse
from wiredex.catalog.domain.values import PartDefinitionId
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import PartId

pytestmark = pytest.mark.anyio

# The projects bench, as catalog names it: the same UUID under catalog's own type.
CATALOG_BENCH = CatalogWorkspaceId(BENCH)
SENSOR = PartId(uuid7())


def naming(world: World, revision: Revision, part_id: PartId, designators: str) -> None:
    line = a_line(revision, part_id, designators)
    world.work.bom_lines.saved[line.id] = line


async def test_the_boms_naming_a_part_come_in_catalogs_words() -> None:
    world = World()
    greenhouse = world.hold_project("Greenhouse controller")
    station = world.hold_project("Weather station", revision=None)
    station_a = world.hold_revision(station, "A")
    station_b = world.hold_revision(station, "B", minutes=5)
    [greenhouse_a] = [
        r for r in world.work.revisions.saved.values() if r.project_id == greenhouse.id
    ]
    for revision in (station_b, station_a, greenhouse_a):
        naming(world, revision, SENSOR, "U2")
    # A second line of the same part on one revision is still one BOM.
    naming(world, station_a, SENSOR, "U3")

    usage = await BomPartUses(world.list_part_uses).of_part(
        CATALOG_BENCH, PartDefinitionId(SENSOR), 2
    )

    # By project name, then oldest revision first; two named, one more.
    assert usage == PartUsage(
        (
            PartUse(greenhouse.id, "Greenhouse controller", greenhouse_a.id, "A"),
            PartUse(station.id, "Weather station", station_a.id, "A"),
        ),
        3,
    )
    assert usage.more == 1
    # Asked in the caller's workspace, translated into projects'.
    assert world.work.opened_for == [BENCH]


async def test_a_part_no_bom_names_has_no_uses() -> None:
    world = World()
    world.hold_project("Weather station")
    [revision] = world.work.revisions.saved.values()
    naming(world, revision, SENSOR, "U2")

    usage = await BomPartUses(world.list_part_uses).of_part(
        CATALOG_BENCH, PartDefinitionId(uuid7()), 3
    )

    assert usage == PartUsage((), 0)
