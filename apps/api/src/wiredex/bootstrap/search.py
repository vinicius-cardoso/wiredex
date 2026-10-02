"""Wire the search: a source per kind over each module's own `Find…` (19-command-palette,
decision 5).

`search` imports none of catalog, inventory, projects and firmware, and none of them imports it
(the independence contract forbids it): this composition root is the one place that knows them
all. Each source turns its module's records into the search's `SearchHit`s, and runs its
module's unit of work, closed before it answers, so the sources take turns and a request holds
one pooled connection at a time (decision 4).
"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.catalog.application.find import FindCategories, FindParts
from wiredex.catalog.application.parts import DescribeParts
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.values import PartDefinitionId
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork
from wiredex.firmware.application.find import FindFirmware
from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.values import WorkspaceId as FirmwareWorkspaceId
from wiredex.firmware.infrastructure.unit_of_work import SqlFirmwareUnitOfWork
from wiredex.inventory.application.find import FindLocations, FindUnits
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.inventory.infrastructure.unit_of_work import SqlInventoryUnitOfWork
from wiredex.projects.application.find import FindProjects
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork
from wiredex.search.api.router import SearchUseCases
from wiredex.search.application.ports import SearchSource
from wiredex.search.application.search import SearchWorkspace
from wiredex.search.domain.search import SearchHit, SearchKind
from wiredex.search.domain.values import WorkspaceId
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator

type SessionFactory = async_sessionmaker[AsyncSession]


class PartSource:
    """Catalog's parts, each with its manufacturer and part number for a detail."""

    def __init__(self, find: FindParts) -> None:
        self._find = find

    @property
    def kind(self) -> SearchKind:
        return SearchKind.PART

    async def find(self, workspace_id: WorkspaceId, text: str, limit: int) -> list[SearchHit]:
        # The same UUIDs under each module's own names: neither imports the other's domain.
        parts = await self._find(CatalogWorkspaceId(workspace_id), text, limit)
        return [_part_hit(part) for part in parts]


class UnitSource:
    """Inventory's units, each named by its code, with its part's name for a detail.

    The parts are asked of catalog's `DescribeParts` once, after inventory's read has closed, so
    the two transactions never overlap, and not at all when no unit matched (decision 4). A unit
    whose part catalog doesn't answer, in the trash, has no detail.
    """

    def __init__(self, find: FindUnits, describe_parts: DescribeParts) -> None:
        self._find = find
        self._describe_parts = describe_parts

    @property
    def kind(self) -> SearchKind:
        return SearchKind.UNIT

    async def find(self, workspace_id: WorkspaceId, text: str, limit: int) -> list[SearchHit]:
        units = await self._find(InventoryWorkspaceId(workspace_id), text, limit)
        if not units:
            return []
        part_ids = list(dict.fromkeys(PartDefinitionId(unit.part_id) for unit in units))
        parts = await self._describe_parts(CatalogWorkspaceId(workspace_id), part_ids)
        hits: list[SearchHit] = []
        for unit in units:
            described = parts.get(PartDefinitionId(unit.part_id))
            detail = None if described is None else str(described.part.name)
            hits.append(SearchHit(SearchKind.UNIT, unit.id, str(unit.code), detail))
        return hits


class ProjectSource:
    """Projects' projects, each with its tags for a detail."""

    def __init__(self, find: FindProjects) -> None:
        self._find = find

    @property
    def kind(self) -> SearchKind:
        return SearchKind.PROJECT

    async def find(self, workspace_id: WorkspaceId, text: str, limit: int) -> list[SearchHit]:
        projects = await self._find(ProjectsWorkspaceId(workspace_id), text, limit)
        return [_project_hit(project) for project in projects]


class FirmwareSource:
    """Firmware's firmware, each with its board target for a detail."""

    def __init__(self, find: FindFirmware) -> None:
        self._find = find

    @property
    def kind(self) -> SearchKind:
        return SearchKind.FIRMWARE

    async def find(self, workspace_id: WorkspaceId, text: str, limit: int) -> list[SearchHit]:
        firmware = await self._find(FirmwareWorkspaceId(workspace_id), text, limit)
        return [_firmware_hit(one) for one in firmware]


class CategorySource:
    """Catalog's categories; a category has no detail."""

    def __init__(self, find: FindCategories) -> None:
        self._find = find

    @property
    def kind(self) -> SearchKind:
        return SearchKind.CATEGORY

    async def find(self, workspace_id: WorkspaceId, text: str, limit: int) -> list[SearchHit]:
        categories = await self._find(CatalogWorkspaceId(workspace_id), text, limit)
        return [_category_hit(category) for category in categories]


class LocationSource:
    """Inventory's locations, each with its short code for a detail."""

    def __init__(self, find: FindLocations) -> None:
        self._find = find

    @property
    def kind(self) -> SearchKind:
        return SearchKind.LOCATION

    async def find(self, workspace_id: WorkspaceId, text: str, limit: int) -> list[SearchHit]:
        locations = await self._find(InventoryWorkspaceId(workspace_id), text, limit)
        return [_location_hit(location) for location in locations]


def search_use_cases(session_factory: SessionFactory) -> SearchUseCases:
    """The search's use case over the six sources, for the app's router."""
    return SearchUseCases(search_workspace=SearchWorkspace(search_sources(session_factory)))


def search_sources(session_factory: SessionFactory) -> Sequence[SearchSource]:
    """A source per kind, in `SearchKind`'s order, the order they are asked in. Each unit of
    work is its module's own, per workspace, as the module's routes get it: the id reaches both
    of ADR 0007's gates."""

    def catalog(workspace_id: CatalogWorkspaceId) -> SqlCatalogUnitOfWork:
        return SqlCatalogUnitOfWork(session_factory, workspace_id)

    def inventory(workspace_id: InventoryWorkspaceId) -> SqlInventoryUnitOfWork:
        return SqlInventoryUnitOfWork(session_factory, workspace_id)

    # The search only reads, but the unit of work takes the ids a fork's copied lines get, as
    # `bootstrap/trash.py`'s does.
    ids = Uuid7Generator()

    def projects(workspace_id: ProjectsWorkspaceId) -> SqlProjectsUnitOfWork:
        return SqlProjectsUnitOfWork(session_factory, workspace_id, ids)

    def firmware(workspace_id: FirmwareWorkspaceId) -> SqlFirmwareUnitOfWork:
        return SqlFirmwareUnitOfWork(session_factory, workspace_id)

    return [
        PartSource(FindParts(catalog)),
        UnitSource(FindUnits(inventory), DescribeParts(catalog)),
        ProjectSource(FindProjects(projects)),
        FirmwareSource(FindFirmware(firmware)),
        CategorySource(FindCategories(catalog)),
        LocationSource(FindLocations(inventory)),
    ]


def _part_hit(part: PartDefinition) -> SearchHit:
    facts = [str(value) for value in (part.manufacturer, part.mpn) if value is not None]
    return SearchHit(SearchKind.PART, part.id, str(part.name), " · ".join(facts) or None)


def _project_hit(project: Project) -> SearchHit:
    tags = ", ".join(tag.value for tag in project.tags.values)
    return SearchHit(SearchKind.PROJECT, project.id, str(project.name), tags or None)


def _firmware_hit(firmware: Firmware) -> SearchHit:
    return SearchHit(SearchKind.FIRMWARE, firmware.id, str(firmware.name), str(firmware.target))


def _category_hit(category: Category) -> SearchHit:
    return SearchHit(SearchKind.CATEGORY, category.id, str(category.name), None)


def _location_hit(location: Location) -> SearchHit:
    return SearchHit(SearchKind.LOCATION, location.id, str(location.name), str(location.code))
