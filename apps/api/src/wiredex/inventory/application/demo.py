"""The sample inventory a demo bench holds, and putting it back (ADR 0007, requirement 8.6).

A guest may add, move and delete locations, and receive, adjust and move stock however they
like in their own bench, so restoring is not a merge: the workspace's inventory is cleared and
the sample tree and sample stock written again, which is what makes a demo bench look the same
every morning.

Stock points at parts, so this runs *after* catalog's parts are restored (requirement 8.6):
the composition root resolves each sample part's fresh id — catalog mints a new one every
reset — and hands them here through `DemoParts`, so inventory learns the ids it receives into
without importing catalog.

The locations go in through `CreateLocation` and the stock through `ReceiveStock`, exactly the
use cases a location from the form and a receive from the dialog go through, so a rule that
stopped accepting a value would fail the nightly job rather than seed something the app can't.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from wiredex.inventory.application.locations import CreateLocation
from wiredex.inventory.application.movements import ReceiveStock
from wiredex.inventory.application.ports import (
    InventoryUnitOfWork,
    NewLocation,
    Receipt,
)
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.values import (
    LocationName,
    PartId,
    Quantity,
    WorkspaceId,
)

# The composition root resolves a sample part's fresh id from its MPN, since catalog mints a
# new id every reset. A part the demo catalog no longer has simply isn't in the mapping, and
# its stock is skipped: the seeding never invents a receive into a part that isn't there.
# Async, because the answer comes from catalog over the database, read here without importing
# catalog: the mapping arrives already resolved by the composition root.
type DemoParts = Callable[[WorkspaceId], Awaitable[Mapping[str, PartId]]]

# A factory over the workspace, like every inventory use case's, so the clear scopes to the
# one bench (ADR 0007).
type UnitOfWorkFactory = Callable[[WorkspaceId], InventoryUnitOfWork]


@dataclass(frozen=True, slots=True)
class SampleStock:
    """A quantity of the part with this MPN, received into the location with this name."""

    part_mpn: str
    location_name: str
    quantity: int


@dataclass(frozen=True, slots=True)
class SampleLocation:
    """One node of the sample location tree, with the locations under it."""

    name: str
    children: tuple[SampleLocation, ...] = ()


# Small on purpose, and still enough to show what inventory does: a two-level tree so a move
# has somewhere to go, and a parts box beside it so a part can sit in more than one place. The
# codes aren't named here — they are minted per workspace by `CreateLocation`, so a bench's
# first location is always WX-L-0001.
SAMPLE_LOCATIONS: tuple[SampleLocation, ...] = (
    SampleLocation(
        "Lab",
        children=(SampleLocation("Cabinet A", children=(SampleLocation("Drawer 3"),)),),
    ),
    SampleLocation("Parts box"),
)

# Received into the sample tree above, for a couple of the demo catalog's lot-counted parts.
# The 4k7 resistor sits in two places, so its total is a sum across lots (requirement 7.1) and
# there is stock to move between drawers in the journey. The MPNs match catalog's sample parts.
SAMPLE_STOCK: tuple[SampleStock, ...] = (
    SampleStock("RC0805FR-074K7L", "Drawer 3", 150),
    SampleStock("RC0805FR-074K7L", "Parts box", 30),
    SampleStock("CRCW060310K0FKEA", "Drawer 3", 200),
    SampleStock("GRM188R71H104KA93D", "Parts box", 100),
)


class RestoreSampleInventory:
    """Puts one demo bench's sample locations and stock back, whatever the guest did to them.

    Part of the nightly `wiredex demo reset` (ADR 0011), run after catalog's parts return
    (requirement 8.6). Which workspaces are demo benches is identity's to answer and which id a
    sample part now carries is catalog's, so the composition root asks both and hands the
    answers here: inventory imports neither module (design §3).
    """

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        create_location: CreateLocation,
        receive_stock: ReceiveStock,
        demo_parts: DemoParts,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._create_location = create_location
        self._receive_stock = receive_stock
        self._demo_parts = demo_parts

    async def __call__(self, workspace_id: WorkspaceId) -> int:
        """Restores the bench's sample inventory and returns how many locations it ended with.

        The clear is one transaction; the locations and stock then go in through their own use
        cases, each its own transaction, so the codes are minted gap-free from the start. The
        workspace it is opened for is the only one any step can touch (ADR 0007).
        """
        await self._clear(workspace_id)
        locations = await self._seed_locations(workspace_id)
        await self._seed_stock(workspace_id, locations)
        return len(locations)

    async def _clear(self, workspace_id: WorkspaceId) -> None:
        """Everything the bench holds, in foreign-key order: the ledger and balances point at
        lots, lots and the counter at nothing, locations at their parents (RESTRICT), so the
        movements go first and the locations last, all in this workspace only."""
        async with self._unit_of_work(workspace_id) as work:
            await work.clear()
            await work.commit()

    async def _seed_locations(self, workspace_id: WorkspaceId) -> dict[str, Location]:
        """The sample tree, created through `CreateLocation` so each node is minted a code.

        Returns the locations by name, which the stock step reads to receive into them. Names
        are unique across the sample tree, so a name is enough to point a receipt at a place.
        """
        by_name: dict[str, Location] = {}
        for sample in SAMPLE_LOCATIONS:
            await self._create_tree(workspace_id, sample, parent=None, by_name=by_name)
        return by_name

    async def _create_tree(
        self,
        workspace_id: WorkspaceId,
        sample: SampleLocation,
        parent: Location | None,
        by_name: dict[str, Location],
    ) -> None:
        location = await self._create_location(
            workspace_id,
            NewLocation(LocationName(sample.name), None if parent is None else parent.id),
        )
        by_name[sample.name] = location
        for child in sample.children:
            await self._create_tree(workspace_id, child, location, by_name)

    async def _seed_stock(self, workspace_id: WorkspaceId, locations: dict[str, Location]) -> None:
        """Receive the sample stock, skipping any part the demo catalog no longer holds.

        The part ids come from the composition root, resolved from catalog after its parts
        were restored (requirement 8.6): a receipt into a part that isn't in the mapping is
        skipped rather than invented, so a change to the sample catalog can't break the reset.
        """
        parts = await self._demo_parts(workspace_id)
        for stock in SAMPLE_STOCK:
            part_id = parts.get(stock.part_mpn)
            if part_id is None:
                continue
            await self._receive_stock(
                workspace_id,
                Receipt(
                    part_id=part_id,
                    location_id=locations[stock.location_name].id,
                    quantity=Quantity(stock.quantity),
                ),
            )


def part_ids_by_mpn(pairs: Sequence[tuple[str | None, PartId]]) -> dict[str, PartId]:
    """The (MPN, id) pairs the composition root read from catalog, as a mapping by MPN.

    Parts without an MPN are dropped: the sample stock names parts by MPN, and every sample
    part carries one. A small helper so the wiring in `bootstrap` stays a one-liner.
    """
    return {mpn: part_id for mpn, part_id in pairs if mpn is not None}
