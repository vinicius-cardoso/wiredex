"""Wire the catalog module: every use case over Postgres, and its deletion guard over projects.

Catalog imports no other module (the independence contract): whether a bill of materials
names a part is projects' to answer, so this composition root answers catalog's `PartUses`
port over projects' `ListPartUses` (09's decision 13), in projects' own transaction.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Settings
from wiredex.catalog.api.router import CatalogUseCases
from wiredex.catalog.application.attributes import (
    DefineAttribute,
    GetCategorySchema,
    RemoveAttribute,
    UpdateAttribute,
)
from wiredex.catalog.application.categories import (
    CreateCategory,
    DeleteCategory,
    ListCategories,
    MoveCategory,
    RenameCategory,
    SetCategoryStocking,
    SetCategoryTracking,
)
from wiredex.catalog.application.demo import RestoreSampleCatalog
from wiredex.catalog.application.parts import (
    DefinePart,
    DeletePart,
    GetPart,
    ListParts,
    UpdatePart,
)
from wiredex.catalog.application.pinouts import GetPinout, ReplacePinout
from wiredex.catalog.application.search import CategoryFacets, SearchParts
from wiredex.catalog.domain.usage import PartUsage, PartUse
from wiredex.catalog.domain.values import PartDefinitionId, WorkspaceId
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork
from wiredex.projects.application.bom import ListPartUses
from wiredex.projects.domain.values import PartId as ProjectsPartId
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator

type SessionFactory = async_sessionmaker[AsyncSession]


class BomPartUses:
    """Catalog's `PartUses` over projects' `ListPartUses`: the BOMs naming a part, in
    catalog's words, so `DeletePart` can refuse to delete it (09's requirement 8.1)."""

    def __init__(self, list_part_uses: ListPartUses) -> None:
        self._list_part_uses = list_part_uses

    async def of_part(
        self, workspace_id: WorkspaceId, part_id: PartDefinitionId, limit: int
    ) -> PartUsage:
        # The same UUIDs under each module's own names: neither imports the other's domain.
        found = await self._list_part_uses(
            ProjectsWorkspaceId(workspace_id), ProjectsPartId(part_id), limit
        )
        uses = tuple(
            PartUse(use.project_id, str(use.project_name), use.revision_id, str(use.revision_label))
            for use in found.uses
        )
        return PartUsage(uses, found.total)


def catalog_use_cases(session_factory: SessionFactory) -> CatalogUseCases:
    """The catalog use cases, wired to Postgres (for the web app)."""

    def unit_of_work(workspace_id: WorkspaceId) -> SqlCatalogUnitOfWork:
        # One unit of work per workspace, which is what carries the id to both of ADR
        # 0007's gates: the repositories filter on it and Postgres reads it in its policies.
        return SqlCatalogUnitOfWork(session_factory, workspace_id)

    clock, ids = SystemClock(), Uuid7Generator()

    def projects_unit_of_work(workspace_id: ProjectsWorkspaceId) -> SqlProjectsUnitOfWork:
        # Its own use case over projects' own unit of work: nothing here forms a loop with
        # projects' wiring, which holds catalog's `DescribeParts` the same way.
        return SqlProjectsUnitOfWork(session_factory, workspace_id, ids)

    part_uses = BomPartUses(ListPartUses(projects_unit_of_work))
    return CatalogUseCases(
        create_category=CreateCategory(unit_of_work, clock, ids),
        rename_category=RenameCategory(unit_of_work),
        move_category=MoveCategory(unit_of_work),
        set_category_tracking=SetCategoryTracking(unit_of_work),
        set_category_stocking=SetCategoryStocking(unit_of_work),
        delete_category=DeleteCategory(unit_of_work),
        list_categories=ListCategories(unit_of_work),
        define_attribute=DefineAttribute(unit_of_work, ids),
        update_attribute=UpdateAttribute(unit_of_work),
        remove_attribute=RemoveAttribute(unit_of_work),
        get_category_schema=GetCategorySchema(unit_of_work),
        define_part=DefinePart(unit_of_work, clock, ids),
        update_part=UpdatePart(unit_of_work, clock),
        get_part=GetPart(unit_of_work),
        list_parts=ListParts(unit_of_work),
        delete_part=DeletePart(unit_of_work, part_uses),
        get_pinout=GetPinout(unit_of_work),
        replace_pinout=ReplacePinout(unit_of_work, clock),
        search_parts=SearchParts(unit_of_work),
        category_facets=CategoryFacets(unit_of_work),
    )


@asynccontextmanager
async def restore_sample_catalog_use_case(
    settings: Settings,
) -> AsyncIterator[RestoreSampleCatalog]:
    """RestoreSampleCatalog over Postgres, for one run of `wiredex demo reset` (ADR 0011)."""
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        yield RestoreSampleCatalog(
            lambda workspace_id: SqlCatalogUnitOfWork(session_factory, workspace_id),
            SystemClock(),
            Uuid7Generator(),
        )
    finally:
        await engine.dispose()
