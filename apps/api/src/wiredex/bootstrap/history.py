"""Wire the history module: its unit of work over Postgres, its use cases, and the modules it asks
about the records it shows and hands its restores to.

The database records every change through `record_history()` (17-history, decision 1); this file
is what reads them back. `history` imports none of catalog, inventory, projects and firmware (the
independence contract forbids it): `RecordDirectory` asks each module's own *get* use case
whether a record is live, so a timeline answers 404 exactly where the record's page does.
"""

from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Settings
from wiredex.catalog.api.router import CatalogUseCases
from wiredex.catalog.application.parts import PartRevision
from wiredex.catalog.domain.errors import CatalogError, PartNotFoundError
from wiredex.catalog.domain.part import PartDetails
from wiredex.catalog.domain.values import (
    CategoryId,
    Manufacturer,
    Mpn,
    Package,
    PartDefinitionId,
    PartName,
)
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.firmware.api.router import FirmwareUseCases
from wiredex.firmware.domain.errors import FirmwareError, FirmwareNotFoundError
from wiredex.firmware.domain.firmware import FirmwareDetails
from wiredex.firmware.domain.values import BoardTarget, FirmwareId, FirmwareName, Framework
from wiredex.firmware.domain.values import Description as FirmwareDescription
from wiredex.firmware.domain.values import WorkspaceId as FirmwareWorkspaceId
from wiredex.history.api.router import HistoryUseCases
from wiredex.history.application.history import (
    ClearHistory,
    ListActivity,
    ListTimeline,
    RestoreVersion,
)
from wiredex.history.domain.errors import NotRestorableError, RecordNotFoundError
from wiredex.history.domain.history import RESTORE_REASON, RecordKind, RecordRef
from wiredex.history.domain.restore import PutBack
from wiredex.history.domain.values import WorkspaceId
from wiredex.history.infrastructure.unit_of_work import SqlHistoryUnitOfWork
from wiredex.inventory.api.router import InventoryUseCases
from wiredex.inventory.domain.errors import InventoryError, UnitNotFoundError
from wiredex.inventory.domain.values import Mac, Serial, UnitId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.projects.api.router import ProjectsUseCases
from wiredex.projects.domain.errors import ProjectNotFoundError, ProjectsError
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.values import Description as ProjectDescription
from wiredex.projects.domain.values import ProjectId, ProjectName, Tags
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.shared_kernel.infrastructure.change_context import changing_for
from wiredex.trash.api.router import TrashUseCases
from wiredex.trash.domain.errors import TrashItemNotFoundError
from wiredex.trash.domain.trash import TrashKind
from wiredex.trash.domain.values import WorkspaceId as TrashWorkspaceId

type SessionFactory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class HistoryModules:
    """The modules whose records history shows and restores, as the app already wired them."""

    catalog: CatalogUseCases
    inventory: InventoryUseCases
    projects: ProjectsUseCases
    firmware: FirmwareUseCases
    trash: TrashUseCases


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


class Restorers:
    """History's `VersionRestorers` over each module's own edit, run under the reason `restore`
    so the trigger marks the change it writes as one (requirements 4.1, 4.2).

    The snapshot is turned into the module's values here, which is where a value the module no
    longer takes is refused, with the module's sentence; the module then refuses what its form
    would (a taken name or MPN, a category gone, values its schema won't take). A record the
    module no longer holds is a 404. Each edit is its module's own transaction.
    """

    def __init__(self, modules: HistoryModules) -> None:
        self._modules = modules

    async def put_back(self, workspace_id: WorkspaceId, plan: PutBack) -> None:
        with changing_for(RESTORE_REASON), _refused_as_not_restorable():
            await self._put_back(workspace_id, plan.record, plan.fields)

    async def take_out_of_trash(self, workspace_id: WorkspaceId, record: RecordRef) -> None:
        trash = self._modules.trash
        with changing_for(RESTORE_REASON):
            try:
                await trash.restore_from_trash(
                    TrashWorkspaceId(workspace_id), TrashKind(record.kind.value), record.id
                )
            except TrashItemNotFoundError as error:
                # Restored or deleted for good since: nothing in the trash to bring back (4.3).
                raise NotRestorableError(f"{_named(record)} isn't in the trash any more") from error

    async def _put_back(
        self, workspace_id: WorkspaceId, record: RecordRef, fields: Mapping[str, object]
    ) -> None:
        modules = self._modules
        match record.kind:
            case RecordKind.PART:
                await modules.catalog.update_part(
                    CatalogWorkspaceId(workspace_id), PartDefinitionId(record.id), _part(fields)
                )
            case RecordKind.UNIT:
                await modules.inventory.relabel_unit(
                    InventoryWorkspaceId(workspace_id),
                    UnitId(record.id),
                    _given(Serial, fields.get("serial")),
                    _given(Mac, fields.get("mac")),
                )
            case RecordKind.PROJECT:
                await modules.projects.update_project(
                    ProjectsWorkspaceId(workspace_id), ProjectId(record.id), _project(fields)
                )
            case RecordKind.FIRMWARE:
                await modules.firmware.update_firmware(
                    FirmwareWorkspaceId(workspace_id), FirmwareId(record.id), _firmware(fields)
                )
            case RecordKind.CATEGORY | RecordKind.LOCATION:  # pragma: no cover - never planned
                raise NotRestorableError("only a part, a unit, a project or a firmware")


def history_use_cases(session_factory: SessionFactory, modules: HistoryModules) -> HistoryUseCases:
    """History's use cases over Postgres, asking `modules` about the records it shows and
    handing them its restores."""
    unit_of_work = _history_unit_of_work(session_factory)
    return HistoryUseCases(
        list_activity=ListActivity(unit_of_work),
        list_timeline=ListTimeline(unit_of_work, RecordDirectory(modules)),
        restore_version=RestoreVersion(unit_of_work, Restorers(modules)),
    )


@contextmanager
def _refused_as_not_restorable() -> Iterator[None]:
    """A module's not-found error as history's 404, anything else it refuses as a 409 with its
    own sentence (requirement 4.4)."""
    try:
        yield
    except (
        PartNotFoundError,
        UnitNotFoundError,
        ProjectNotFoundError,
        FirmwareNotFoundError,
    ) as error:
        raise RecordNotFoundError(str(error)) from error
    except (CatalogError, InventoryError, ProjectsError, FirmwareError) as error:
        raise NotRestorableError(str(error)) from error


def _part(fields: Mapping[str, object]) -> PartRevision:
    details = PartDetails(
        PartName(str(fields["name"])),
        _given(Manufacturer, fields.get("manufacturer")),
        _given(Mpn, fields.get("mpn")),
        _given(Package, fields.get("package")),
    )
    attributes = fields.get("attributes")
    return PartRevision(
        details=details,
        raw_attributes=attributes if isinstance(attributes, dict) else {},
        category_id=CategoryId(UUID(str(fields["category_id"]))),
    )


def _project(fields: Mapping[str, object]) -> ProjectDetails:
    tags = fields.get("tags")
    return ProjectDetails(
        name=ProjectName(str(fields["name"])),
        description=_given(ProjectDescription, fields.get("description")),
        tags=Tags.of(str(tag) for tag in tags) if isinstance(tags, list) else Tags.none(),
    )


def _firmware(fields: Mapping[str, object]) -> FirmwareDetails:
    return FirmwareDetails(
        name=FirmwareName(str(fields["name"])),
        target=BoardTarget(str(fields["target"])),
        framework=Framework(str(fields["framework"])),
        description=_given(FirmwareDescription, fields.get("description")),
    )


def _given[T](make: Callable[[str], T], value: object) -> T | None:
    """The module's value for a snapshot's text, or None for a field the version left empty."""
    return None if value is None or value == "" else make(str(value))


def _named(record: RecordRef) -> str:
    return record.label or f"that {record.kind.value}"


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
