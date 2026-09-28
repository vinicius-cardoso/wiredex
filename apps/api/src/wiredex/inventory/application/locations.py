"""The location tree: create, rename, move, delete, and read the whole thing.

Mirrors the catalog category use cases. The tree rules the domain can't answer alone — is
that name taken among these siblings, is this parent one of my own descendants, how deep does
my subtree reach — all need a look around, so these use cases read the tree and pass it in.
"""

from collections import Counter, defaultdict
from collections.abc import Callable

from wiredex.inventory.application.ports import (
    InventoryUnitOfWork,
    LocationNode,
    NewLocation,
    ShortCodeKind,
)
from wiredex.inventory.domain.errors import (
    DuplicateLocationNameError,
    LocationInUseError,
    LocationNotFoundError,
)
from wiredex.inventory.domain.location import Location, check_depth
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    ShortCode,
    WorkspaceId,
)
from wiredex.shared_kernel.application.ports import Clock, IdGenerator

type UnitOfWorkFactory = Callable[[WorkspaceId], InventoryUnitOfWork]


class CreateLocation:
    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock, ids: IdGenerator) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids

    async def __call__(self, workspace_id: WorkspaceId, new: NewLocation) -> Location:
        async with self._unit_of_work(workspace_id) as work:
            parent = await _parent(work, new.parent_id)
            await _check_name_free(work, new.parent_id, new.name)
            check_depth(await _position_under(work, parent))
            # Mint the code once, inside the transaction, gap-free per workspace (2.6).
            number = await work.short_codes.next(ShortCodeKind.LOCATION)
            location = Location(
                LocationId(self._ids.new_id()),
                workspace_id,
                new.parent_id,
                ShortCode.for_location(number),
                new.name,
                self._clock.now(),
            )
            await work.locations.add(location)
            await work.commit()
            return location


class RenameLocation:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, location_id: LocationId, name: LocationName
    ) -> Location:
        async with self._unit_of_work(workspace_id) as work:
            location = await load_location(work, location_id)
            # Only a real rename asks whether the name is free, because a location is always
            # its own sibling. The entity decides something changed, so renaming to the name
            # it already has commits nothing (requirement 1.9).
            if location.name != name:
                await _check_name_free(work, location.parent_id, name)
            if location.rename(name):
                await work.commit()
            return location


class MoveLocation:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, location_id: LocationId, parent_id: LocationId | None
    ) -> Location:
        async with self._unit_of_work(workspace_id) as work:
            location = await load_location(work, location_id)
            parent = await _parent(work, parent_id)
            if location.parent_id != parent_id:
                await _check_name_free(work, parent_id, location.name)
            position = await _position_under(work, parent)
            # The entity checks its own depth, but only a reader of the tree knows how many
            # levels of descendants ride along with it (requirement 1.6).
            check_depth(position, below=await _subtree_depth(work, location_id))
            # `position` without the parent itself is the parent's own chain, which is what
            # the entity reads to refuse a move under one of its descendants.
            location.move_under(parent, position[:-1])
            await work.commit()
            return location


class DeleteLocation:
    """Refuses rather than cascades: nothing here deletes data another row points at."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, location_id: LocationId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            location = await load_location(work, location_id)
            # Which of the two blocks it, because that is what the web has to say (1.10).
            if await work.locations.children_of(location_id):
                raise LocationInUseError(f"{location.name} still has locations under it")
            if await work.locations.has_lots(location_id):
                raise LocationInUseError(f"{location.name} still holds stock")
            await work.locations.remove(location)
            await work.commit()


class ListLocations:
    """The whole tree, flat, each node carrying its counts (requirement 1.12)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId) -> list[LocationNode]:
        async with self._unit_of_work(workspace_id) as work:
            locations = await work.locations.all()
            # Every count in one query: asking each location in turn held the connection for
            # a round trip per location, which a tree of a few hundred turned into seconds.
            lots = await work.locations.lot_counts()
            children = Counter(loc.parent_id for loc in locations if loc.parent_id is not None)
            # Siblings come out alphabetically; the web nests them by parent id.
            return [
                LocationNode(location, children[location.id], lots.get(location.id, 0))
                for location in sorted(locations, key=_by_name)
            ]


async def load_location(work: InventoryUnitOfWork, location_id: LocationId) -> Location:
    """The location, or a 404. Another workspace's id is simply not found (requirement 1.7)."""
    location = await work.locations.get(location_id)
    if location is None:
        raise LocationNotFoundError("that location doesn't exist")
    return location


async def _parent(work: InventoryUnitOfWork, parent_id: LocationId | None) -> Location | None:
    """The parent a command names, or None for the root. A named parent has to exist."""
    if parent_id is None:
        return None
    return await load_location(work, parent_id)


async def _check_name_free(
    work: InventoryUnitOfWork, parent_id: LocationId | None, name: LocationName
) -> None:
    """Requirements 1.3 and 1.7, roots included: two roots are siblings of each other."""
    if await work.locations.sibling_named(parent_id, name) is not None:
        where = "at the root" if parent_id is None else "here"
        raise DuplicateLocationNameError(f"there is already a {name} {where}")


async def _position_under(work: InventoryUnitOfWork, parent: Location | None) -> list[LocationId]:
    """The ancestor ids of a location sitting under `parent`: root first, the parent last."""
    if parent is None:
        return []
    above = await work.locations.ancestors(parent.id)
    return [*(ancestor.id for ancestor in above), parent.id]


async def _subtree_depth(work: InventoryUnitOfWork, location_id: LocationId) -> int:
    """How many levels of descendants a location carries, 0 for a leaf.

    The whole tree in one read, level by level: the depth cap keeps it small, and it is
    cheaper than asking the database for the descendants of every move.
    """
    children: dict[LocationId | None, list[LocationId]] = defaultdict(list)
    for location in await work.locations.all():
        children[location.parent_id].append(location.id)
    depth, level = 0, children[location_id]
    while level:
        depth += 1
        level = [child for parent in level for child in children[parent]]
    return depth


def _by_name(location: Location) -> tuple[str, str]:
    # Folded, so *drawer* sits next to *Drawer*; the id breaks a tie so the order of two
    # locations with one name is still stable.
    return location.name.value.casefold(), str(location.id)
