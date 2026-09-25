from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
)
from wiredex.catalog.application.parts import (
    DefinePart,
    DeletePart,
    GetPart,
    ListParts,
    UpdatePart,
)
from wiredex.catalog.domain.values import WorkspaceId
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator


def catalog_use_cases(session_factory: async_sessionmaker[AsyncSession]) -> CatalogUseCases:
    """The catalog use cases, wired to Postgres (for the web app)."""

    def unit_of_work(workspace_id: WorkspaceId) -> SqlCatalogUnitOfWork:
        # One unit of work per workspace, which is what carries the id to both of ADR
        # 0007's gates: the repositories filter on it and Postgres reads it in its policies.
        return SqlCatalogUnitOfWork(session_factory, workspace_id)

    clock, ids = SystemClock(), Uuid7Generator()
    return CatalogUseCases(
        create_category=CreateCategory(unit_of_work, clock, ids),
        rename_category=RenameCategory(unit_of_work),
        move_category=MoveCategory(unit_of_work),
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
        delete_part=DeletePart(unit_of_work),
    )
