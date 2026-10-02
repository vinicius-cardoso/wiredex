"""Wire the history module: its unit of work over Postgres, its use cases, and the modules it asks
about the records it shows.

The database records every change through `record_history()` (17-history, decision 1); this file
is what reads them back. `history` imports none of catalog, inventory, projects and firmware (the
independence contract forbids it): `RecordDirectory` asks each module's own *get* use case
whether a record is live, so a timeline answers 404 exactly where the record's page does.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Settings
from wiredex.catalog.api.router import CatalogUseCases
from wiredex.catalog.domain.errors import PartNotFoundError
from wiredex.catalog.domain.values import PartDefinitionId
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.firmware.api.router import FirmwareUseCases
from wiredex.firmware.domain.errors import FirmwareNotFoundError
from wiredex.firmware.domain.values import FirmwareId
from wiredex.firmware.domain.values import WorkspaceId as FirmwareWorkspaceId
from wiredex.history.api.router import HistoryUseCases
from wiredex.history.application.history import ClearHistory, ListActivity, ListTimeline
from wiredex.history.domain.history import RecordKind
from wiredex.history.domain.values import WorkspaceId
from wiredex.history.infrastructure.unit_of_work import SqlHistoryUnitOfWork
from wiredex.inventory.api.router import InventoryUseCases
from wiredex.inventory.domain.errors import UnitNotFoundError
from wiredex.inventory.domain.values import UnitId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.projects.api.router import ProjectsUseCases
from wiredex.projects.domain.errors import ProjectNotFoundError
from wiredex.projects.domain.values import ProjectId
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId

type SessionFactory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class HistoryModules:
    """The modules whose records history shows, as the app already wired them."""

    catalog: CatalogUseCases
    inventory: InventoryUseCases
    projects: ProjectsUseCases
    firmware: FirmwareUseCases


class RecordDirectory:
    """History's `Records` over each module's *get*: live is what the module answers, so a
    record in the trash, deleted, or another bench's is absent, as on its page (requirement
    3.2). Each read is its module's own transaction, closed before history opens one."""

    def __init__(self, modules: HistoryModules) -> None:
        self._modules = modules

    async def exists(self, workspace_id: WorkspaceId, kind: RecordKind, record_id: UUID) -> bool:
        # The same UUIDs under each module's own names: neither imports the other's domain.
        try:
            await self._get(workspace_id, kind, record_id)
        except PartNotFoundError, UnitNotFoundError, ProjectNotFoundError, FirmwareNotFoundError:
            return False
        return True

    async def _get(self, workspace_id: WorkspaceId, kind: RecordKind, record_id: UUID) -> None:
        modules = self._modules
        match kind:
            case RecordKind.PART:
                part_id = PartDefinitionId(record_id)
                await modules.catalog.get_part(CatalogWorkspaceId(workspace_id), part_id)
            case RecordKind.UNIT:
                unit_id = UnitId(record_id)
                await modules.inventory.get_unit(InventoryWorkspaceId(workspace_id), unit_id)
            case RecordKind.PROJECT:
                project_id = ProjectId(record_id)
                await modules.projects.get_project(ProjectsWorkspaceId(workspace_id), project_id)
            case RecordKind.FIRMWARE:
                firmware_id = FirmwareId(record_id)
                await modules.firmware.get_firmware(FirmwareWorkspaceId(workspace_id), firmware_id)
            case RecordKind.CATEGORY | RecordKind.LOCATION:
                # No page of their own carries a timeline: they show in the feed only (12).
                raise PartNotFoundError("categories and locations have no timeline")


def history_use_cases(session_factory: SessionFactory, modules: HistoryModules) -> HistoryUseCases:
    """History's use cases over Postgres, asking `modules` about the records it shows."""
    unit_of_work = _history_unit_of_work(session_factory)
    return HistoryUseCases(
        list_activity=ListActivity(unit_of_work),
        list_timeline=ListTimeline(unit_of_work, RecordDirectory(modules)),
    )


def _history_unit_of_work(
    session_factory: SessionFactory,
) -> Callable[[WorkspaceId], SqlHistoryUnitOfWork]:
    # One unit of work per workspace, as every module's is: the id reaches both of ADR 0007's
    # gates, the repository's filter and the policies.
    return lambda workspace_id: SqlHistoryUnitOfWork(session_factory, workspace_id)


@asynccontextmanager
async def clear_history_use_case(settings: Settings) -> AsyncIterator[ClearHistory]:
    """ClearHistory over Postgres, for the benches a demo invite or reset has just seeded: a
    bench's history starts empty with its samples (requirement 5.4)."""
    engine = create_engine(settings)
    try:
        yield ClearHistory(_history_unit_of_work(create_session_factory(engine)))
    finally:
        await engine.dispose()
