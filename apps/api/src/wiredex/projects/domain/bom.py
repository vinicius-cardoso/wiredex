"""A revision's bill of materials: its lines, and the rules that look across them.

A line names one part definition (no substitutes before 1.0), the designators it fills, how
many of the part and a note. The BOM is built from the one read a repository makes, under the
project's lock when it is about to change (decision 12), so a designator it finds free stays
free until the transaction ends.
"""

from dataclasses import dataclass, replace
from datetime import datetime

from wiredex.projects.domain.designators import Designator, Designators
from wiredex.projects.domain.errors import (
    BomLineNotFoundError,
    DesignatorTakenError,
    InvalidBomNotesError,
    InvalidLineQuantityError,
    QuantityMismatchError,
    TooManyLinesError,
)
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import BomLineId, PartId, RevisionId, WorkspaceId

MAX_LINE_QUANTITY = 10_000
MAX_NOTES_LENGTH = 500
MAX_LINES = 500


@dataclass(frozen=True, slots=True)
class LineQuantity:
    """How many of a line's part: a whole number from 1 to 10,000."""

    value: int

    def __post_init__(self) -> None:
        if not 1 <= self.value <= MAX_LINE_QUANTITY:
            raise InvalidLineQuantityError(
                f"a line without designators needs a quantity from 1 to {MAX_LINE_QUANTITY:,}"
            )


@dataclass(frozen=True, slots=True)
class BomNotes:
    """A line's note: trimmed, whitespace collapsed, 1-500 characters. Blank text is no
    note, which the edge reads as None before it gets here (requirement 4.5).

    One line, unlike a revision's notes: it sits in a table cell (*about 2 m of jumpers*).
    """

    value: str

    def __post_init__(self) -> None:
        collapsed = " ".join(self.value.split())
        if not 1 <= len(collapsed) <= MAX_NOTES_LENGTH:
            raise InvalidBomNotesError(
                f"a line's notes need between 1 and {MAX_NOTES_LENGTH} characters"
            )
        object.__setattr__(self, "value", collapsed)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class LineContent:
    """What a line says, and everything an edit replaces (requirement 4.9)."""

    part_id: PartId
    designators: Designators
    quantity: LineQuantity
    notes: BomNotes | None = None

    def __post_init__(self) -> None:
        # Held here, not only in `of`, so no path builds a line whose count and designators
        # disagree: the report sums the stored quantity.
        count = len(self.designators)
        if count and self.quantity.value != count:
            raise _mismatch(self.designators, self.quantity.value)

    @classmethod
    def of(
        cls,
        part_id: PartId,
        designators: Designators,
        quantity: int | None,
        notes: BomNotes | None,
    ) -> LineContent:
        """Decision 7: with designators the quantity is their count, and a quantity given
        that differs is `QuantityMismatchError`; without, a quantity from 1 to 10,000 is
        required (`InvalidLineQuantityError`)."""
        count = len(designators)
        if count:
            if quantity is not None and quantity != count:
                raise _mismatch(designators, quantity)
            return cls(part_id, designators, LineQuantity(count), notes)
        if quantity is None:
            raise InvalidLineQuantityError(
                f"a line without designators needs a quantity from 1 to {MAX_LINE_QUANTITY:,}"
            )
        return cls(part_id, designators, LineQuantity(quantity), notes)


@dataclass(frozen=True, slots=True)
class BomLine:
    """One line of a BOM. Immutable: an edit is a new value with the same id, which is what
    lets the repository write only the difference (decision 8)."""

    id: BomLineId
    workspace_id: WorkspaceId
    revision_id: RevisionId
    content: LineContent
    created_at: datetime

    @classmethod
    def on(
        cls, revision: Revision, line_id: BomLineId, content: LineContent, now: datetime
    ) -> BomLine:
        """A new line of the revision: its workspace and revision come from the revision."""
        return cls(line_id, revision.workspace_id, revision.id, content, now)

    def revised(self, content: LineContent) -> BomLine:
        return replace(self, content=content)

    def copied_to(self, target: Revision, line_id: BomLineId) -> BomLine:
        """The same content on a fork, created with it (decision 15): the fork's date and ids
        minted in the source's order keep the copies in the source's order."""
        return BomLine(line_id, target.workspace_id, target.id, self.content, target.created_at)


@dataclass(frozen=True, slots=True)
class PartNeed:
    """What a BOM needs of one part: its lines' quantities summed, and how many lines."""

    part_id: PartId
    quantity: int
    lines: int


@dataclass(frozen=True, slots=True)
class BillOfMaterials:
    """One revision's lines, oldest first, as the repository reads them. Its rules: at most
    500 lines, and no designator on two of them (docs/architecture.md §5, "designators
    unique"). The same part may sit on several lines (decision 9)."""

    revision_id: RevisionId
    lines: tuple[BomLine, ...] = ()

    def with_line(self, line: BomLine) -> BillOfMaterials:
        """The line after the others: `TooManyLinesError` for a 501st (4.7), and
        `DesignatorTakenError` naming the first of its designators another line holds, and
        that line (4.6)."""
        if len(self.lines) >= MAX_LINES:
            raise TooManyLinesError(f"a revision's BOM holds at most {MAX_LINES} lines")
        self._ensure_free(line)
        return replace(self, lines=(*self.lines, line))

    def replacing(self, line: BomLine) -> BillOfMaterials:
        """The line's new value in its place; its own designators don't count against it."""
        self.line(line.id)
        self._ensure_free(line)
        return replace(
            self, lines=tuple(line if held.id == line.id else held for held in self.lines)
        )

    def without(self, line_id: BomLineId) -> BillOfMaterials:
        self.line(line_id)
        return replace(self, lines=tuple(held for held in self.lines if held.id != line_id))

    def line(self, line_id: BomLineId) -> BomLine:
        """`BomLineNotFoundError` for a line that isn't on this BOM, another revision's line
        included (requirement 4.12)."""
        for held in self.lines:
            if held.id == line_id:
                return held
        raise BomLineNotFoundError("that line isn't on this revision's BOM")

    def line_with(self, designator: Designator) -> BomLine | None:
        """The line holding a designator: what 11's pin references resolve through."""
        return next((held for held in self.lines if designator in held.content.designators), None)

    def needs(self) -> tuple[PartNeed, ...]:
        """Per part, in the order each first appears: what the report reads and 10 reserves."""
        totals: dict[PartId, PartNeed] = {}
        for held in self.lines:
            part_id = held.content.part_id
            before = totals.get(part_id, PartNeed(part_id, 0, 0))
            totals[part_id] = PartNeed(
                part_id, before.quantity + held.content.quantity.value, before.lines + 1
            )
        return tuple(totals.values())

    def part_ids(self) -> tuple[PartId, ...]:
        return tuple(need.part_id for need in self.needs())

    def _ensure_free(self, line: BomLine) -> None:
        """Every designator of the line held by no other line; the first taken is named."""
        # One map rather than a scan per designator: a line may hold 256 of them.
        holders = {
            designator: held
            for held in self.lines
            if held.id != line.id
            for designator in held.content.designators
        }
        for designator in line.content.designators:
            holder = holders.get(designator)
            if holder is not None:
                taken = holder.content.designators.text()
                raise DesignatorTakenError(
                    f"{designator} is already on the line {taken}",
                    item=str(designator),
                    line_id=holder.id,
                    line=taken,
                )


def _mismatch(designators: Designators, quantity: int) -> QuantityMismatchError:
    count = len(designators)
    are = "is 1 designator" if count == 1 else f"are {count} designators"
    return QuantityMismatchError(
        f"{designators.text()} {are}, so the quantity is {count}, not {quantity}"
    )
