"""Catalog's deletion guard over Postgres, as `wiredex_app`, through the real wiring.

Catalog asks projects which BOMs name a part through `bootstrap/catalog.py`'s `BomPartUses`,
in projects' own transaction, and refuses to delete a part any of them names (09's
requirements 8.1 and 8.2). Only the real wiring shows the two modules' units of work agreeing
on the workspace and the ids.
"""

from collections.abc import AsyncIterator
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.projects import projects_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.application.parts import NewPart
from wiredex.catalog.domain.errors import PartInUseError, PartNotFoundError
from wiredex.catalog.domain.part import PartDetails
from wiredex.catalog.domain.values import CategoryName, PartName
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.projects.application.ports import NewBomLine, NewRevision
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.values import PartId, ProjectName, WorkspaceId

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BENCH = WorkspaceId(uuid7())
TABLES = "bom_designators, bom_lines, revisions, projects, pins, part_definitions, categories"


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
        await connection.execute(text(f"TRUNCATE {TABLES} CASCADE"))


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


async def test_a_part_on_two_boms_is_kept_until_its_lines_are_gone(app: AsyncEngine) -> None:
    session_factory = create_session_factory(app)
    catalog, projects = catalog_use_cases(session_factory), projects_use_cases(session_factory)
    here = CatalogWorkspaceId(BENCH)
    sensors = await catalog.create_category(here, NewCategory(CategoryName("Sensors")))
    sensor = await catalog.define_part(
        here, NewPart(sensors.category.id, PartDetails(PartName("BME280")))
    )
    station = await projects.create_project(BENCH, ProjectDetails(ProjectName("Weather station")))
    a = station.revisions.latest
    assert a is not None
    line = await projects.add_bom_line(
        BENCH, a.id, NewBomLine(PartId(sensor.id), Designators.parse("U2"))
    )
    # The fork copies A's line, so B's BOM names the sensor too.
    b = await projects.fork_revision(BENCH, a.id, NewRevision())

    with pytest.raises(PartInUseError, match="on 2 bills of materials") as refused:
        await catalog.delete_part(here, sensor.id)

    named = [(use.project_name, use.revision_label) for use in refused.value.usage.uses]
    assert named == [("Weather station", "A"), ("Weather station", "B")]
    assert refused.value.usage.more == 0
    assert (await catalog.get_part(here, sensor.id)).part.name == sensor.name

    [copied] = (await projects.get_bom(BENCH, b.id)).bom.lines
    await projects.remove_bom_line(BENCH, a.id, line.id)
    await projects.remove_bom_line(BENCH, b.id, copied.id)
    await catalog.delete_part(here, sensor.id)

    with pytest.raises(PartNotFoundError):
        await catalog.get_part(here, sensor.id)
