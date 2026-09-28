"""Preview and import a sheet: plan every row against the workspace, then carry the plan out
in one transaction, but only when it is clean and is still the plan the preview showed.

The preview writes nothing. It opens the intake unit of work, reads, and leaves without
`commit()`, so nothing is staged between it and the import (design decision 3). The import
sends the same text back with the preview's digest and is planned again from scratch. Any
problem refuses it (decision 5), and a plan with another digest refuses it too (decision 4),
both before a single write. Then every row is carried out in order, the catalog's half through
`work.catalog` and the stock through the receipts' `perform`, and all of it is committed once
(requirements 8.1-8.3, 12.1).
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
from wiredex.inventory.domain.errors import ImportChangedError, IntakeRefusedError
from wiredex.inventory.domain.intake import (
    CellProblem,
    DefinesPart,
    ImportPlan,
    ImportSummary,
    KnownPart,
    NamesPart,
    PartDraft,
    PartOutcome,
    PlannedRow,
    ProblemCode,
    ReceivesLot,
    ReceivesUnits,
    SameAsRow,
    SheetBook,
    StockOutcome,
    UnitLabels,
    plan_stock,
)
from wiredex.inventory.domain.location import LocationPaths
from wiredex.inventory.domain.sheet import Column, Sheet, SheetRow, read_sheet
from wiredex.inventory.domain.unit import Unit
from wiredex.inventory.domain.values import Mac, Serial, WorkspaceId


@dataclass(frozen=True, slots=True)
class ImportedPart:
    """A part an import defined, and the row that defined it."""

    row: int
    part: KnownPart


@dataclass(frozen=True, slots=True)
class ImportResult:
    """What an import did (requirement 8.5): the preview's summary, the parts it defined with
    their rows, and the units it received, codes minted."""

    summary: ImportSummary
    parts: tuple[ImportedPart, ...]
    units: tuple[Unit, ...]


async def plan_import(work: IntakeUnitOfWork, sheet: Sheet) -> ImportPlan:
    """What every row of the sheet will do, and what stands in its way. Reads only.

    The location tree is read once, whatever the number of rows (requirement 12.2); the
    catalog's port reads its tree and each schema once per transaction on its side.
    """
    planner = _Planner(work, LocationPaths(await work.locations.all()))
    return ImportPlan.of([await planner.plan(row) for row in sheet.rows])


class PreviewImport:
    """Plan a sheet against the workspace and write nothing (requirements 7.1, 7.2, 7.5).

    Problems are the preview's answer, not a refusal: only a sheet that can't be read at all
    raises, `SheetUnreadableError`, and it does so before a unit of work is opened.
    """

    def __init__(self, unit_of_work: IntakeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, text: str) -> ImportPlan:
        sheet = read_sheet(text)
        async with self._unit_of_work(workspace_id) as work:
            # Left without `commit()`: a preview only ever reads (design decision 3).
            return await plan_import(work, sheet)


class ImportSheet:
    """Import a sheet whose preview answered `digest`, all in one transaction (requirement 8).

    The sheet is planned again from scratch. A plan with any problem is refused with them all
    (`IntakeRefusedError`, 8.2), and a plan whose digest isn't the one sent is refused as
    changed (`ImportChangedError`, 8.3), both before anything is written. Otherwise each row,
    in order, defines its part through the catalog, names a stored one, or uses the part an
    earlier row defined, then receives its stock: one `RECEIVE` per row, through the receive
    paths the dialogs use (8.6). One `commit()` keeps it all, and leaving without it keeps
    none of it (8.4).
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

    async def __call__(self, workspace_id: WorkspaceId, text: str, digest: str) -> ImportResult:
        sheet = read_sheet(text)
        async with self._unit_of_work(workspace_id) as work:
            plan = await plan_import(work, sheet)
            _confirm(plan, digest)
            result = await self._carry_out(workspace_id, work, plan)
            await work.commit()
            return result

    async def _carry_out(
        self, workspace_id: WorkspaceId, work: IntakeUnitOfWork, plan: ImportPlan
    ) -> ImportResult:
        parts: dict[int, KnownPart] = {}
        defined: list[ImportedPart] = []
        units: list[Unit] = []
        for row in plan.rows:
            part = await _part_of(work, row.part, parts)
            parts[row.row] = part
            if isinstance(row.part, DefinesPart):
                defined.append(ImportedPart(row.row, part))
            units.extend(await self._receive(workspace_id, work, part, row.stock))
        return ImportResult(plan.summary, tuple(defined), tuple(units))

    async def _receive(
        self,
        workspace_id: WorkspaceId,
        work: IntakeUnitOfWork,
        part: KnownPart,
        stock: StockOutcome | None,
    ) -> tuple[Unit, ...]:
        """The row's one receipt in the open transaction. The plan read how the part is
        counted from the catalog, in this transaction, so no `Parts` check."""
        if isinstance(stock, ReceivesLot):
            receipt = Receipt(part.id, stock.location.id, stock.quantity)
            await self._receive_stock.perform(workspace_id, work, receipt)
            return ()
        if isinstance(stock, ReceivesUnits):
            labelled = tuple(NewUnit(unit.serial, unit.mac) for unit in stock.units)
            received = await self._receive_units.perform(
                workspace_id, work, UnitReceipt(part.id, stock.location.id, labelled)
            )
            return received.units
        return ()


_REFUSED = "the sheet can't be imported as it is"
_CHANGED = "the sheet's outcome changed since its preview; preview it again"


def _confirm(plan: ImportPlan, digest: str) -> None:
    """Refuse a plan that isn't clean, or isn't the one the preview showed."""
    if plan.problems:
        raise IntakeRefusedError(plan.problems, _REFUSED)
    if plan.digest != digest:
        raise ImportChangedError(_CHANGED)


async def _part_of(
    work: IntakeUnitOfWork, outcome: PartOutcome, parts: dict[int, KnownPart]
) -> KnownPart:
    """The part a row stocks: the one it defines now, the stored one it names, or the one
    the earlier row it repeats has just defined."""
    if isinstance(outcome, NamesPart):
        return outcome.part
    if isinstance(outcome, SameAsRow):
        return parts[outcome.row]
    return await work.catalog.define(outcome.draft)


class _Planner:
    """One sheet's planning: the location tree read once, what earlier rows have planned,
    and the rows that define a part, whose flag a later row giving the same part uses."""

    __slots__ = ("_book", "_defines", "_locations", "_work")

    def __init__(self, work: IntakeUnitOfWork, locations: LocationPaths) -> None:
        self._work = work
        self._locations = locations
        self._book = SheetBook()
        self._defines: dict[int, DefinesPart] = {}

    async def plan(self, row: SheetRow) -> PlannedRow:
        draft = PartDraft.of_row(row)
        review = await self._work.catalog.review(draft)
        part, first_row, part_problems = self._part(row.number, draft, review)
        tracked, not_stocked = _flags(part)
        stock, stock_problems = plan_stock(row, tracked, not_stocked, self._locations)
        stock, label_problems = await self._labelled(stock, part, first_row, row.number)
        problems = (*_overflow(row), *part_problems, *stock_problems, *label_problems)
        return PlannedRow(row.number, part, stock, problems)

    def _part(
        self, number: int, draft: PartDraft, review: PartReview
    ) -> tuple[PartOutcome, int, tuple[CellProblem, ...]]:
        """What the row does with a part, the first row that resolves to that part, and the
        part cells' problems (requirements 5.1-5.3).

        A row naming a stored part, or the part an earlier row defines, isn't judged on the
        part cells it doesn't use, so only a row defining a part has problems of its own.
        """
        first = self._book.part_row(review.identity, number)
        if review.existing is not None:
            return NamesPart(review.existing), first, ()
        if first != number:
            earlier = self._defines.get(first)
            if earlier is None:
                return SameAsRow(first, None, None), first, ()
            return SameAsRow(first, earlier.tracked_individually, earlier.not_stocked), first, ()
        defines = DefinesPart(
            draft,
            review.category_id,
            review.category_path,
            review.identity,
            review.tracked_individually,
            review.not_stocked,
        )
        self._defines[number] = defines
        return defines, first, tuple(problem.on_row(number) for problem in review.problems)

    async def _labelled(
        self, stock: StockOutcome | None, part: PartOutcome, first_row: int, number: int
    ) -> tuple[StockOutcome | None, tuple[CellProblem, ...]]:
        """The units' serials and MACs against earlier rows and the stored units (6.9).

        A taken label is the row's problem, and its stock is then planned as nothing, as
        `plan_stock` plans nothing for stock whose cells don't read: a row's stock is what
        an import will receive.
        """
        if not isinstance(stock, ReceivesUnits):
            return stock, ()
        problems: list[CellProblem] = []
        for labels in stock.units:
            problems.extend(await self._label_problems(labels, part, first_row, number))
        return (None if problems else stock), tuple(problems)

    async def _label_problems(
        self, labels: UnitLabels, part: PartOutcome, first_row: int, number: int
    ) -> tuple[CellProblem, ...]:
        """At most one problem per label: the earlier row that gives it, or else the stored
        unit that holds it."""
        earlier = {
            problem.column: problem
            for problem in self._book.label_problems(first_row, labels, number)
        }
        serial = earlier.get(Column.SERIAL) or await self._stored_serial(labels.serial, part)
        mac = earlier.get(Column.MAC) or await self._stored_mac(labels.mac)
        return tuple(problem.on_row(number) for problem in (serial, mac) if problem is not None)

    async def _stored_serial(self, serial: Serial | None, part: PartOutcome) -> CellProblem | None:
        """A serial is unique per part, so only a stored part can already hold one: a part
        this sheet defines has no units yet."""
        if serial is None or not isinstance(part, NamesPart):
            return None
        if not await self._work.units.serial_taken(part.part.id, serial):
            return None
        return CellProblem(
            None,
            Column.SERIAL,
            ProblemCode.SERIAL_TAKEN,
            f"another unit of {part.part.name} already has the serial {serial}",
        )

    async def _stored_mac(self, mac: Mac | None) -> CellProblem | None:
        """A MAC is unique across the workspace, whichever part holds it."""
        if mac is None or not await self._work.units.mac_taken(mac):
            return None
        return CellProblem(
            None,
            Column.MAC,
            ProblemCode.MAC_TAKEN,
            f"another unit in this workspace already has the MAC {mac}",
        )


def _flags(part: PartOutcome) -> tuple[bool | None, bool | None]:
    """How the row's part is counted and whether it is stocked at all: a stored part's own
    flags, or the flags its category resolves to; None while that category is a problem."""
    if isinstance(part, NamesPart):
        return part.part.tracked_individually, part.part.not_stocked
    return part.tracked_individually, part.not_stocked


def _overflow(row: SheetRow) -> tuple[CellProblem, ...]:
    """A non-blank cell past the header's columns (requirement 4.7). Most often a cell
    holding the separator unquoted, which shifts every cell after it, so it comes first."""
    if not row.overflows:
        return ()
    message = "this row has a cell past the last column: a cell holding the separator needs quotes"
    return (CellProblem(row.number, None, ProblemCode.EXTRA_CELLS, message),)
