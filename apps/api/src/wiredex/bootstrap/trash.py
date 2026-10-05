"""Wire the trash: a bin per kind over each module's own trash use cases (16's decision 8).

`trash` imports none of catalog, inventory, projects and firmware, and none of them imports it
(the independence contract forbids it): this composition root is the one place that knows them
all. Each bin turns its module's records into the trash's `TrashedItem`, and its not-found error,
which its trash use cases raise for a record that isn't in the trash, into
`TrashItemNotFoundError`. Each runs its module's unit of work and closes it before it answers, so
the bins take turns and a request holds one pooled connection at a time.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.catalog.application.categories import UnitOfWorkFactory as CatalogUnitOfWorkFactory
from wiredex.catalog.application.parts import DescribeParts, PartDescription, PartIdsNamed
from wiredex.catalog.application.trash import (
    DeletePartForGood,
    EmptyPartTrash,
    ListTrashedParts,
    RestorePart,
)
from wiredex.catalog.domain.errors import PartNotFoundError
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.values import PartDefinitionId
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork
from wiredex.firmware.application.firmware import UnitOfWorkFactory as FirmwareUnitOfWorkFactory
from wiredex.firmware.application.trash import (
    DeleteFirmwareForGood,
    EmptyFirmwareTrash,
    ListTrashedFirmware,
    RestoreFirmware,
)
from wiredex.firmware.domain.errors import FirmwareNotFoundError
from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.values import FirmwareId
from wiredex.firmware.domain.values import WorkspaceId as FirmwareWorkspaceId
from wiredex.firmware.infrastructure.unit_of_work import SqlFirmwareUnitOfWork
from wiredex.inventory.application.trash import (
    DeleteUnitForGood,
    EmptyUnitTrash,
    ListTrashedUnits,
    RestoreUnit,
)
from wiredex.inventory.application.units import UnitOfWorkFactory as InventoryUnitOfWorkFactory
from wiredex.inventory.domain.errors import UnitNotFoundError
from wiredex.inventory.domain.unit import Unit
from wiredex.inventory.domain.values import PartId as InventoryPartId
from wiredex.inventory.domain.values import UnitId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.inventory.infrastructure.unit_of_work import SqlInventoryUnitOfWork
from wiredex.projects.application.projects import UnitOfWorkFactory as ProjectsUnitOfWorkFactory
from wiredex.projects.application.trash import (
    DeleteProjectForGood,
    EmptyProjectTrash,
    ListTrashedProjects,
    RestoreProject,
)
from wiredex.projects.domain.errors import ProjectNotFoundError
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.values import ProjectId
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork
from wiredex.shared_kernel.domain.trash import TrashedSlice
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator
from wiredex.trash.api.router import TrashUseCases
from wiredex.trash.application.ports import TrashBin
from wiredex.trash.application.trash import (
    DeleteFromTrash,
    EmptyTrash,
    ListTrash,
    RestoreFromTrash,
)
from wiredex.trash.domain.errors import TrashItemNotFoundError
from wiredex.trash.domain.trash import TrashedItem, TrashKind
from wiredex.trash.domain.values import WorkspaceId

type SessionFactory = async_sessionmaker[AsyncSession]


class PartTrash:
    """Catalog's parts in the trash, each with its MPN for a detail."""

    def __init__(self, unit_of_work: CatalogUnitOfWorkFactory) -> None:
        self._trashed = ListTrashedParts(unit_of_work)
        self._restore = RestorePart(unit_of_work)
        self._delete = DeletePartForGood(unit_of_work)
        self._empty = EmptyPartTrash(unit_of_work)

    @property
    def kind(self) -> TrashKind:
        return TrashKind.PART

    async def newest(
        self, workspace_id: WorkspaceId, count: int, text: str | None
    ) -> TrashedSlice[TrashedItem]:
        # The same UUIDs under each module's own names: neither imports the other's domain.
        parts = await self._trashed(CatalogWorkspaceId(workspace_id), count, text)
        return TrashedSlice(tuple(_part_item(part) for part in parts.items), parts.total)

    async def restore(self, workspace_id: WorkspaceId, item_id: UUID) -> None:
        with _absent_is_not_in_trash(PartNotFoundError):
            await self._restore(CatalogWorkspaceId(workspace_id), PartDefinitionId(item_id))

    async def delete(self, workspace_id: WorkspaceId, item_id: UUID) -> None:
        with _absent_is_not_in_trash(PartNotFoundError):
            await self._delete(CatalogWorkspaceId(workspace_id), PartDefinitionId(item_id))

    async def empty(self, workspace_id: WorkspaceId) -> None:
        await self._empty(CatalogWorkspaceId(workspace_id))


class UnitTrash:
    """Inventory's units in the trash, each named by its code, with its part's name for a detail.

    A text matches a unit's code or its part's name, which only the catalog knows: catalog's
    `PartIdsNamed` names the live parts whose name holds it first, and inventory's read matches
    the units against those ids. The page's parts are then asked of catalog's `DescribeParts`.
    Each transaction closes before the next opens, so they never overlap. A unit whose part
    catalog doesn't answer, deleted or in the trash too, has no detail, and no name to match.
    """

    def __init__(
        self,
        unit_of_work: InventoryUnitOfWorkFactory,
        part_ids_named: PartIdsNamed,
        describe_parts: DescribeParts,
    ) -> None:
        self._trashed = ListTrashedUnits(unit_of_work)
        self._restore = RestoreUnit(unit_of_work)
        self._delete = DeleteUnitForGood(unit_of_work)
        self._empty = EmptyUnitTrash(unit_of_work)
        self._part_ids_named = part_ids_named
        self._describe_parts = describe_parts

    @property
    def kind(self) -> TrashKind:
        return TrashKind.UNIT

    async def newest(
        self, workspace_id: WorkspaceId, count: int, text: str | None
    ) -> TrashedSlice[TrashedItem]:
        named = (
            frozenset()
            if text is None
            else await self._part_ids_named(CatalogWorkspaceId(workspace_id), text)
        )
        units = await self._trashed(
            InventoryWorkspaceId(workspace_id),
            count,
            text,
            frozenset(InventoryPartId(part_id) for part_id in named),
        )
        part_ids = list(dict.fromkeys(PartDefinitionId(unit.part_id) for unit in units.items))
        parts = await self._describe_parts(CatalogWorkspaceId(workspace_id), part_ids)
        items = tuple(
            _unit_item(unit, parts.get(PartDefinitionId(unit.part_id))) for unit in units.items
        )
        return TrashedSlice(items, units.total)

    async def restore(self, workspace_id: WorkspaceId, item_id: UUID) -> None:
        with _absent_is_not_in_trash(UnitNotFoundError):
            await self._restore(InventoryWorkspaceId(workspace_id), UnitId(item_id))

    async def delete(self, workspace_id: WorkspaceId, item_id: UUID) -> None:
        with _absent_is_not_in_trash(UnitNotFoundError):
            await self._delete(InventoryWorkspaceId(workspace_id), UnitId(item_id))

    async def empty(self, workspace_id: WorkspaceId) -> None:
        await self._empty(InventoryWorkspaceId(workspace_id))


class ProjectTrash:
    """Projects' projects in the trash, with their revisions; a project has no detail."""

    def __init__(self, unit_of_work: ProjectsUnitOfWorkFactory) -> None:
        self._trashed = ListTrashedProjects(unit_of_work)
        self._restore = RestoreProject(unit_of_work)
        self._delete = DeleteProjectForGood(unit_of_work)
        self._empty = EmptyProjectTrash(unit_of_work)

    @property
    def kind(self) -> TrashKind:
        return TrashKind.PROJECT

    async def newest(
        self, workspace_id: WorkspaceId, count: int, text: str | None
    ) -> TrashedSlice[TrashedItem]:
        projects = await self._trashed(ProjectsWorkspaceId(workspace_id), count, text)
        return TrashedSlice(
            tuple(_project_item(project) for project in projects.items), projects.total
        )

    async def restore(self, workspace_id: WorkspaceId, item_id: UUID) -> None:
        with _absent_is_not_in_trash(ProjectNotFoundError):
            await self._restore(ProjectsWorkspaceId(workspace_id), ProjectId(item_id))

    async def delete(self, workspace_id: WorkspaceId, item_id: UUID) -> None:
        with _absent_is_not_in_trash(ProjectNotFoundError):
            await self._delete(ProjectsWorkspaceId(workspace_id), ProjectId(item_id))

    async def empty(self, workspace_id: WorkspaceId) -> None:
        await self._empty(ProjectsWorkspaceId(workspace_id))


class FirmwareTrash:
    """Firmware's firmware in the trash, with its versions, each with its target for a detail."""

    def __init__(self, unit_of_work: FirmwareUnitOfWorkFactory) -> None:
        self._trashed = ListTrashedFirmware(unit_of_work)
        self._restore = RestoreFirmware(unit_of_work)
        self._delete = DeleteFirmwareForGood(unit_of_work)
        self._empty = EmptyFirmwareTrash(unit_of_work)

    @property
    def kind(self) -> TrashKind:
        return TrashKind.FIRMWARE

    async def newest(
        self, workspace_id: WorkspaceId, count: int, text: str | None
    ) -> TrashedSlice[TrashedItem]:
        firmware = await self._trashed(FirmwareWorkspaceId(workspace_id), count, text)
        return TrashedSlice(tuple(_firmware_item(one) for one in firmware.items), firmware.total)

    async def restore(self, workspace_id: WorkspaceId, item_id: UUID) -> None:
        with _absent_is_not_in_trash(FirmwareNotFoundError):
            await self._restore(FirmwareWorkspaceId(workspace_id), FirmwareId(item_id))

    async def delete(self, workspace_id: WorkspaceId, item_id: UUID) -> None:
        with _absent_is_not_in_trash(FirmwareNotFoundError):
            await self._delete(FirmwareWorkspaceId(workspace_id), FirmwareId(item_id))

    async def empty(self, workspace_id: WorkspaceId) -> None:
        await self._empty(FirmwareWorkspaceId(workspace_id))


def trash_use_cases(session_factory: SessionFactory) -> TrashUseCases:
    """The trash's use cases over the four bins, for the app's router."""
    bins = trash_bins(session_factory)
    return TrashUseCases(
        list_trash=ListTrash(bins),
        restore_from_trash=RestoreFromTrash(bins),
        delete_from_trash=DeleteFromTrash(bins),
        empty_trash=EmptyTrash(bins),
    )


def trash_bins(session_factory: SessionFactory) -> Sequence[TrashBin]:
    """A bin per kind, in `TrashKind`'s order, which is the order emptying takes them in. Each
    unit of work is its module's own, per workspace, as the module's routes get it: the id
    reaches both of ADR 0007's gates."""

    def catalog(workspace_id: CatalogWorkspaceId) -> SqlCatalogUnitOfWork:
        return SqlCatalogUnitOfWork(session_factory, workspace_id)

    def inventory(workspace_id: InventoryWorkspaceId) -> SqlInventoryUnitOfWork:
        return SqlInventoryUnitOfWork(session_factory, workspace_id)

    # The trash only restores and deletes, but the unit of work takes the ids a fork's copied
    # lines get, as `bootstrap/files.py`'s does.
    ids = Uuid7Generator()

    def projects(workspace_id: ProjectsWorkspaceId) -> SqlProjectsUnitOfWork:
        return SqlProjectsUnitOfWork(session_factory, workspace_id, ids)

    def firmware(workspace_id: FirmwareWorkspaceId) -> SqlFirmwareUnitOfWork:
        return SqlFirmwareUnitOfWork(session_factory, workspace_id)

    return [
        PartTrash(catalog),
        UnitTrash(inventory, PartIdsNamed(catalog), DescribeParts(catalog)),
        ProjectTrash(projects),
        FirmwareTrash(firmware),
    ]


@contextmanager
def _absent_is_not_in_trash(missing: type[Exception]) -> Iterator[None]:
    """The module's not-found error as the trash's own, a 404 whatever the module: its trash use
    cases raise it for a record that isn't in the trash, another bench's included."""
    try:
        yield
    except missing as error:
        raise TrashItemNotFoundError(str(error)) from error


def _part_item(part: PartDefinition) -> TrashedItem:
    return TrashedItem(
        kind=TrashKind.PART,
        id=part.id,
        name=str(part.name),
        detail=None if part.mpn is None else str(part.mpn),
        trashed_at=_moved_at(part.trashed_at),
    )


def _unit_item(unit: Unit, part: PartDescription | None) -> TrashedItem:
    return TrashedItem(
        kind=TrashKind.UNIT,
        id=unit.id,
        name=str(unit.code),
        detail=None if part is None else str(part.part.name),
        trashed_at=_moved_at(unit.trashed_at),
    )


def _project_item(project: Project) -> TrashedItem:
    return TrashedItem(
        kind=TrashKind.PROJECT,
        id=project.id,
        name=str(project.name),
        detail=None,
        trashed_at=_moved_at(project.trashed_at),
    )


def _firmware_item(firmware: Firmware) -> TrashedItem:
    return TrashedItem(
        kind=TrashKind.FIRMWARE,
        id=firmware.id,
        name=str(firmware.name),
        detail=str(firmware.target),
        trashed_at=_moved_at(firmware.trashed_at),
    )


def _moved_at(trashed_at: datetime | None) -> datetime:
    """When a record read from the trash moved there: always set, since the trash's reads answer
    only rows whose `trashed_at` is."""
    if trashed_at is None:  # pragma: no cover - the trash's reads answer only trashed rows
        raise ValueError("a record read from the trash has no trashed_at")
    return trashed_at
