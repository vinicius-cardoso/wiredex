"""Quick-add: a part and its first stock from one short form, in one transaction.

A quick-add is a one-row intake with no sheet and no digest (design, "Quick-add"). The part
half is the catalog's to judge and write, through `work.catalog`, which the composition root
binds to this unit of work's transaction (design decision 2). The stock half is inventory's
own receipt, `ReceiveStock.perform` or `ReceiveUnits.perform` inside that same transaction.
So one `commit()` keeps the part and its stock together, and a refusal of either keeps
neither (requirements 1.4, 12.1).
"""

from dataclasses import dataclass

from wiredex.inventory.application.movements import ReceiveStock
from wiredex.inventory.application.ports import (
    IntakeUnitOfWork,
    IntakeUnitOfWorkFactory,
    PartReview,
    Receipt,
)
from wiredex.inventory.application.units import NewUnit, ReceiveUnits, UnitReceipt
from wiredex.inventory.domain.errors import IntakeRefusedError, PartAlreadyDefinedError
from wiredex.inventory.domain.intake import (
    CellProblem,
    KnownPart,
    PartDraft,
    ProblemCode,
    not_stocked_problem,
    quantity_problem,
)
from wiredex.inventory.domain.lot import StockBalance
from wiredex.inventory.domain.sheet import Column
from wiredex.inventory.domain.unit import Unit
from wiredex.inventory.domain.values import LocationId, PartId, Quantity, WorkspaceId


@dataclass(frozen=True, slots=True)
class QuickStock:
    """Where a quick-add's first stock goes and how much: one location and one quantity, a
    lot's pieces or a number of units (design decision 11)."""

    location_id: LocationId
    quantity: int


@dataclass(frozen=True, slots=True)
class QuickAddition:
    """One quick-add: a part as typed, and optionally its first stock."""

    part: PartDraft  # category_id set, category_path None
    stock: QuickStock | None = None
    pinout_from: PartId | None = None  # a duplicate's source (requirement 3.2)


@dataclass(frozen=True, slots=True)
class QuickAdded:
    """What a quick-add added: the part, and the lot's balance or the units it received."""

    part: KnownPart
    balance: StockBalance | None  # a lot receipt's
    units: tuple[Unit, ...]  # a unit receipt's, codes minted


_REFUSED = "the part can't be added as it is"


class QuickAdd:
    """Define a part and receive its first stock, in one unit of work (requirement 1).

    The catalog reviews the draft first. A stored part already holding the manufacturer and
    part number is a 409 naming it (`PartAlreadyDefinedError`, 1.6), so the owner opens that
    part instead of fixing a form they no longer need. Otherwise every problem is gathered:
    the review's, a location the workspace doesn't hold (1.9), and the quantity against how
    the review says the part is counted (1.8), or, for a consumable, any stock at all (09's
    requirement 2.5). They are refused together as one 422
    (`IntakeRefusedError`, 1.5). With none, the part is defined, a duplicate's pinout copied
    on the way (3.2), its stock received as a lot or as units with blank labels (1.2, 1.3),
    and everything committed once.
    """

    def __init__(
        self,
        unit_of_work: IntakeUnitOfWorkFactory,
        receive_stock: ReceiveStock,
        receive_units: ReceiveUnits,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._receive_stock = receive_stock
        self._receive_units = receive_units

    async def __call__(self, workspace_id: WorkspaceId, addition: QuickAddition) -> QuickAdded:
        async with self._unit_of_work(workspace_id) as work:
            review = await work.catalog.review(addition.part)
            if review.existing is not None:
                raise _already_defined(addition.part, review.existing)
            stock = await _stock_problems(work, addition.stock, review)
            problems = (*review.problems, *stock)
            if problems:
                raise IntakeRefusedError(problems, _REFUSED)
            part = await work.catalog.define(addition.part, addition.pinout_from)
            added = await self._receive(workspace_id, work, part, addition.stock)
            await work.commit()
            return added

    async def _receive(
        self,
        workspace_id: WorkspaceId,
        work: IntakeUnitOfWork,
        part: KnownPart,
        stock: QuickStock | None,
    ) -> QuickAdded:
        """One receipt in the open transaction, by how the defined part is counted. The
        caller has just asked its own catalog, in this transaction, so no `Parts` check."""
        if stock is None:
            return QuickAdded(part, None, ())
        if part.tracked_individually:
            blank = (NewUnit(),) * stock.quantity
            received = await self._receive_units.perform(
                workspace_id, work, UnitReceipt(part.id, stock.location_id, blank)
            )
            return QuickAdded(part, None, received.units)
        balance = await self._receive_stock.perform(
            workspace_id, work, Receipt(part.id, stock.location_id, Quantity(stock.quantity))
        )
        return QuickAdded(part, balance, ())


async def _stock_problems(
    work: IntakeUnitOfWork, stock: QuickStock | None, review: PartReview
) -> tuple[CellProblem, ...]:
    """What stands in the stock's way: a location this workspace doesn't hold, and a quantity
    out of range for the part's kind. While the category is a problem the kind is unknown,
    and only the bounds both kinds share are checked. A consumable takes no stock at all, so
    that is its one problem, on the quantity (09's requirement 2.5)."""
    if stock is None:
        return ()
    if review.not_stocked:
        return (not_stocked_problem(Column.QUANTITY),)
    found = (
        await _location_problem(work, stock.location_id),
        quantity_problem(stock.quantity, review.tracked_individually),
    )
    return tuple(problem for problem in found if problem is not None)


async def _location_problem(work: IntakeUnitOfWork, location_id: LocationId) -> CellProblem | None:
    # Another workspace's location isn't in this unit of work, so it is unknown too (10.2).
    if await work.locations.get(location_id) is not None:
        return None
    return CellProblem(
        None, Column.LOCATION, ProblemCode.UNKNOWN_LOCATION, "that location doesn't exist"
    )


def _already_defined(draft: PartDraft, part: KnownPart) -> PartAlreadyDefinedError:
    """The 409 naming the part that holds the number, in the design's words. The review only
    names a stored part when the draft gives a part number."""
    number = " ".join((draft.mpn or "").split()) or "this part number"
    return PartAlreadyDefinedError(part, f"{number} is already the part {part.name}")
