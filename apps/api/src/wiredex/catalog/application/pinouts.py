"""A part's pin table: read it, or replace the whole of it.

Two use cases and no third, because a pinout is replaced whole and never patched pin by pin
(design §2): the editor edits a table and saves that table, so "no two pins share a number"
is checked in one place — the collection — and a half-saved pinout can't exist.

Both start from the part. The pins are the part's, so asking for them is asking for the
part, and a part of another workspace is simply not found (requirement 1.9).
"""

from collections.abc import Callable, Sequence

from wiredex.catalog.application.parts import load_part
from wiredex.catalog.application.ports import PinoutUnitOfWork
from wiredex.catalog.domain.pinout import Pinout, RawPin
from wiredex.catalog.domain.values import PartDefinitionId, WorkspaceId
from wiredex.shared_kernel.application.ports import Clock

# The catalog's factory, narrowed to the units of work that hold pins: `UnitOfWorkFactory`
# again once `pinouts` is on `CatalogUnitOfWork` (see ports.py).
type PinoutUnitOfWorkFactory = Callable[[WorkspaceId], PinoutUnitOfWork]


class GetPinout:
    """The part's pins in their saved order; a part with none reads as an empty pinout (1.2)."""

    def __init__(self, unit_of_work: PinoutUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, part_id: PartDefinitionId) -> Pinout:
        async with self._unit_of_work(workspace_id) as work:
            part = await load_part(work, part_id)
            return await work.pinouts.of_part(part.id)


class ReplacePinout:
    """The rows the editor saved, as the part's whole pinout (requirements 1.3 to 1.6)."""

    def __init__(self, unit_of_work: PinoutUnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self, workspace_id: WorkspaceId, part_id: PartDefinitionId, rows: Sequence[RawPin]
    ) -> Pinout:
        async with self._unit_of_work(workspace_id) as work:
            part = await load_part(work, part_id)
            # Read before anything is written, so a refused table leaves no trace at all
            # (requirement 1.3) — the same reason a part is validated before it is stored.
            pinout = Pinout.parse(rows)
            if pinout == await work.pinouts.of_part(part.id):
                # The same table saved twice, as a form resubmitted sends it: answered with
                # what is stored, and committing nothing (requirement 1.6).
                return pinout
            await work.pinouts.replace(part.id, pinout)
            # Clearing the table is a change like any other (requirements 1.4 and 1.5), and
            # the part is what carries the timestamp: its pins are part of what it is.
            part.pinout_changed(self._clock.now())
            await work.commit()
            return pinout
