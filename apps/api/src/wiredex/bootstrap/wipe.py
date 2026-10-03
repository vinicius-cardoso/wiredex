"""Empty a workspace of everything it holds, for `wiredex workspace clear`.

The account, its login and the workspace itself stay; what goes is every module's data in
it: files, firmware, projects, stock, the catalog, and last the history the clearing itself
wrote. It is the clearing half of `wiredex demo reset`, without the samples coming back, and
this composition root is the one place that knows every module (ADR 0001). Each module's rows
go in an order of its own, in its own transaction; no key crosses modules, so the order
between modules only follows who names whom.
"""

from uuid import UUID

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.files import clear_workspace_use_case
from wiredex.bootstrap.history import clear_history_use_case
from wiredex.bootstrap.settings import Settings
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork
from wiredex.files.domain.values import WorkspaceId as FilesWorkspaceId
from wiredex.firmware.domain.values import WorkspaceId as FirmwareWorkspaceId
from wiredex.firmware.infrastructure.unit_of_work import SqlFirmwareUnitOfWork
from wiredex.history.domain.values import WorkspaceId as HistoryWorkspaceId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.inventory.infrastructure.unit_of_work import SqlInventoryUnitOfWork
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator


async def wipe_workspace(settings: Settings, workspace_id: UUID) -> None:
    """Everything in the workspace, gone. The stored files first, so nothing is left without
    a row to find it by."""
    async with clear_workspace_use_case(settings) as clear_files:
        await clear_files(FilesWorkspaceId(workspace_id))
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        # Firmware names revisions and units, projects name parts and hold stock, stock names
        # parts: each goes before what it names.
        async with SqlFirmwareUnitOfWork(sessions, FirmwareWorkspaceId(workspace_id)) as firmware:
            await firmware.clear()
            await firmware.commit()
        async with SqlProjectsUnitOfWork(
            sessions, ProjectsWorkspaceId(workspace_id), Uuid7Generator()
        ) as projects:
            await projects.clear()
            await projects.commit()
        async with SqlInventoryUnitOfWork(sessions, InventoryWorkspaceId(workspace_id)) as stock:
            await stock.clear()
            await stock.commit()
        async with SqlCatalogUnitOfWork(sessions, CatalogWorkspaceId(workspace_id)) as catalog:
            # Parts first: a category with parts under it can't go.
            await catalog.parts.remove_all()
            await catalog.attribute_definitions.remove_all()
            await catalog.categories.remove_all()
            await catalog.commit()
    finally:
        await engine.dispose()
    # Last: the clearing above was recorded as changes, and they describe nothing kept.
    async with clear_history_use_case(settings) as clear_history:
        await clear_history(HistoryWorkspaceId(workspace_id))
