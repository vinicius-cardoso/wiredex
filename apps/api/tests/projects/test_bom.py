from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from support.bom import NOW, PART_POOL, a_line, a_revision, line_contents
from wiredex.projects.domain.bom import (
    MAX_LINE_QUANTITY,
    MAX_LINES,
    MAX_NOTES_LENGTH,
    BillOfMaterials,
    BomLine,
    BomNotes,
    LineContent,
    LineQuantity,
    PartNeed,
)
from wiredex.projects.domain.designators import Designator, Designators
from wiredex.projects.domain.errors import (
    BomLineNotFoundError,
    DesignatorTakenError,
    InvalidBomNotesError,
    InvalidLineQuantityError,
    ProjectsError,
    QuantityMismatchError,
    TooManyLinesError,
)
from wiredex.projects.domain.values import BomLineId, PartId, RevisionStatus

RESISTOR, CAPACITOR, SENSOR, WIRE = PART_POOL


class TestLineQuantity:
    @pytest.mark.parametrize("quantity", [1, 10, MAX_LINE_QUANTITY])
    def test_accepts_a_whole_number_from_1_to_10000(self, quantity: int) -> None:
        assert LineQuantity(quantity).value == quantity

    @pytest.mark.parametrize("quantity", [0, -1, MAX_LINE_QUANTITY + 1])
    def test_refuses_anything_else(self, quantity: int) -> None:
        with pytest.raises(InvalidLineQuantityError, match="from 1 to 10,000"):
            LineQuantity(quantity)


class TestBomNotes:
    def test_is_trimmed_and_has_its_whitespace_collapsed(self) -> None:
        assert BomNotes("  I²C   pull-ups \n").value == "I²C pull-ups"

    def test_accepts_500_characters_once_collapsed_and_refuses_501(self) -> None:
        assert len(BomNotes(" " + "x" * MAX_NOTES_LENGTH + "  ").value) == MAX_NOTES_LENGTH
        assert len(BomNotes("x " * 250).value) == 499
        with pytest.raises(InvalidBomNotesError, match="between 1 and 500 characters"):
            BomNotes("x" * (MAX_NOTES_LENGTH + 1))

    @pytest.mark.parametrize("text", ["", "   ", "\t\n"])
    def test_blank_is_refused_the_edge_reads_it_as_none(self, text: str) -> None:
        with pytest.raises(InvalidBomNotesError):
            BomNotes(text)


class TestLineContent:
    def test_with_designators_the_quantity_is_their_count(self) -> None:
        content = LineContent.of(RESISTOR, Designators.parse("R1-4"), None, None)
        assert content.quantity == LineQuantity(4)

    def test_a_quantity_equal_to_the_count_is_accepted(self) -> None:
        content = LineContent.of(RESISTOR, Designators.parse("R1-4"), 4, None)
        assert content.quantity == LineQuantity(4)

    def test_a_quantity_differing_from_the_count_is_refused(self) -> None:
        with pytest.raises(QuantityMismatchError) as refused:
            LineContent.of(RESISTOR, Designators.parse("R1-4"), 5, None)
        assert str(refused.value) == "R1–R4 are 4 designators, so the quantity is 4, not 5"

    def test_one_designator_is_counted_in_the_singular(self) -> None:
        with pytest.raises(QuantityMismatchError, match="U1 is 1 designator, so the quantity is 1"):
            LineContent.of(SENSOR, Designators.parse("U1"), 2, None)

    def test_without_designators_a_quantity_is_required(self) -> None:
        with pytest.raises(InvalidLineQuantityError):
            LineContent.of(WIRE, Designators.none(), None, None)

    @pytest.mark.parametrize(("quantity", "accepted"), [(0, False), (1, True), (10_000, True)])
    def test_without_designators_the_quantity_is_bounded(
        self, quantity: int, accepted: bool
    ) -> None:
        if accepted:
            content = LineContent.of(WIRE, Designators.none(), quantity, None)
            assert content.quantity.value == quantity
        else:
            with pytest.raises(InvalidLineQuantityError):
                LineContent.of(WIRE, Designators.none(), quantity, None)

    def test_10001_pieces_are_refused(self) -> None:
        with pytest.raises(InvalidLineQuantityError):
            LineContent.of(WIRE, Designators.none(), MAX_LINE_QUANTITY + 1, None)

    def test_cant_be_built_with_a_count_its_designators_disagree_with(self) -> None:
        with pytest.raises(QuantityMismatchError):
            LineContent(RESISTOR, Designators.parse("R1, R2"), LineQuantity(3))


class TestBomLine:
    def test_on_takes_the_revisions_workspace_and_id(self) -> None:
        revision = a_revision()
        content = LineContent.of(SENSOR, Designators.parse("U1"), None, None)

        line = BomLine.on(revision, BomLineId(uuid7()), content, NOW)

        assert line.workspace_id == revision.workspace_id
        assert line.revision_id == revision.id
        assert line.content == content
        assert line.created_at == NOW

    def test_revised_keeps_its_id_revision_and_date(self) -> None:
        line = a_line(a_revision(), RESISTOR, "R1-3")
        content = LineContent.of(CAPACITOR, Designators.parse("C1"), None, BomNotes("decoupling"))

        revised = line.revised(content)

        assert (revised.id, revised.revision_id, revised.created_at) == (
            line.id,
            line.revision_id,
            line.created_at,
        )
        assert revised.content == content

    def test_copied_to_takes_the_targets_revision_workspace_and_date(self) -> None:
        line = a_line(a_revision(), RESISTOR, "R1-3")
        fork = a_revision(label="B")
        fork.created_at = NOW + timedelta(days=1)

        copy = line.copied_to(fork, BomLineId(uuid7()))

        assert copy.id != line.id
        assert (copy.workspace_id, copy.revision_id, copy.created_at) == (
            fork.workspace_id,
            fork.id,
            fork.created_at,
        )
        assert copy.content == line.content


class TestBillOfMaterials:
    def test_a_line_lands_after_the_others(self) -> None:
        revision = a_revision()
        first = a_line(revision, RESISTOR, "R1-3")
        second = a_line(revision, CAPACITOR, "C1", minutes=1)

        bom = BillOfMaterials(revision.id).with_line(first).with_line(second)

        assert bom.lines == (first, second)

    def test_a_taken_designator_is_refused_naming_the_line_holding_it(self) -> None:
        revision = a_revision()
        holder = a_line(revision, RESISTOR, "R5-7")
        bom = BillOfMaterials(revision.id, (holder,))

        with pytest.raises(DesignatorTakenError) as refused:
            bom.with_line(a_line(revision, RESISTOR, "R1, R7, R6"))

        assert str(refused.value) == "R6 is already on the line R5–R7"
        assert refused.value.item == "R6"
        assert refused.value.line_id == holder.id
        assert refused.value.line == "R5–R7"

    def test_two_lines_may_name_the_same_part(self) -> None:
        revision = a_revision()
        pull_ups = a_line(revision, RESISTOR, "R1, R2")
        divider = a_line(revision, RESISTOR, "R3, R4", minutes=1)

        bom = BillOfMaterials(revision.id).with_line(pull_ups).with_line(divider)

        assert len(bom.lines) == 2

    def test_holds_500_lines_and_refuses_a_501st(self) -> None:
        revision = a_revision()
        lines = tuple(a_line(revision, WIRE, quantity=1) for _ in range(MAX_LINES))
        bom = BillOfMaterials(revision.id, lines)

        with pytest.raises(TooManyLinesError, match="at most 500 lines"):
            bom.with_line(a_line(revision, WIRE, quantity=1))
        refilled = bom.without(lines[0].id).with_line(a_line(revision, WIRE, quantity=1))
        assert len(refilled.lines) == MAX_LINES

    def test_an_edit_keeps_its_own_designators_and_its_place(self) -> None:
        revision = a_revision()
        first = a_line(revision, RESISTOR, "R1-3")
        second = a_line(revision, CAPACITOR, "C1", minutes=1)
        bom = BillOfMaterials(revision.id, (first, second))
        edited = first.revised(
            LineContent.of(RESISTOR, Designators.parse("R2-4"), None, BomNotes("divider"))
        )

        after = bom.replacing(edited)

        assert after.lines == (edited, second)

    def test_an_edit_onto_another_lines_designator_is_refused(self) -> None:
        revision = a_revision()
        first = a_line(revision, RESISTOR, "R1-3")
        second = a_line(revision, RESISTOR, "R4", minutes=1)
        bom = BillOfMaterials(revision.id, (first, second))

        with pytest.raises(DesignatorTakenError, match="R4 is already on the line R4"):
            bom.replacing(
                first.revised(LineContent.of(RESISTOR, Designators.parse("R1-4"), None, None))
            )

    def test_a_line_that_isnt_on_the_bom_is_not_found(self) -> None:
        revision = a_revision()
        bom = BillOfMaterials(revision.id, (a_line(revision, RESISTOR, "R1"),))
        elsewhere = a_line(a_revision(), RESISTOR, "R1")

        with pytest.raises(BomLineNotFoundError):
            bom.line(elsewhere.id)
        with pytest.raises(BomLineNotFoundError):
            bom.replacing(elsewhere)
        with pytest.raises(BomLineNotFoundError):
            bom.without(elsewhere.id)

    def test_removing_a_line_frees_its_designators(self) -> None:
        revision = a_revision()
        line = a_line(revision, RESISTOR, "R1")
        bom = BillOfMaterials(revision.id, (line,)).without(line.id)

        assert bom.lines == ()
        assert bom.with_line(a_line(revision, CAPACITOR, "R1")).line_with(Designator("R", 1))

    def test_line_with_finds_the_line_holding_a_designator(self) -> None:
        revision = a_revision()
        resistors = a_line(revision, RESISTOR, "R1-4")
        sensor = a_line(revision, SENSOR, "U1", minutes=1)
        bom = BillOfMaterials(revision.id, (resistors, sensor))

        assert bom.line_with(Designator("R", 3)) == resistors
        assert bom.line_with(Designator("U", 1)) == sensor
        assert bom.line_with(Designator("C", 1)) is None

    def test_needs_sum_each_parts_lines_in_first_appearance_order(self) -> None:
        revision = a_revision()
        lines = (
            a_line(revision, SENSOR, "U1"),
            a_line(revision, RESISTOR, "R1, R2", minutes=1),
            a_line(revision, WIRE, quantity=3, minutes=2),
            a_line(revision, RESISTOR, "R3-5", minutes=3),
        )
        bom = BillOfMaterials(revision.id, lines)

        assert bom.needs() == (
            PartNeed(SENSOR, 1, 1),
            PartNeed(RESISTOR, 5, 2),
            PartNeed(WIRE, 3, 1),
        )
        assert bom.part_ids() == (SENSOR, RESISTOR, WIRE)

    def test_an_empty_bom_needs_nothing(self) -> None:
        bom = BillOfMaterials(a_revision(RevisionStatus.BUILT).id)
        assert bom.needs() == ()
        assert bom.part_ids() == ()


# --- Property 5: a line's content is exactly what its rules allow --------------------------


@given(
    designators=st.sampled_from(["", "U1", "R1-4", "C1, C2", "R1-256"]).map(Designators.parse),
    quantity=st.none() | st.integers(-5, 20) | st.integers(MAX_LINE_QUANTITY - 2, 10_005),
    notes=st.text() | st.text(alphabet=" \t\nxé", max_size=MAX_NOTES_LENGTH + 20),
)
def test_a_lines_content_is_exactly_what_its_rules_allow(
    designators: Designators, quantity: int | None, notes: str
) -> None:
    """Property 5: a line's content is exactly what its rules allow.

    For any designators (none or some), any quantity (none, or any integer) and any notes
    text, LineContent.of accepts exactly when the line has designators and the quantity is
    none or their count, or has no designators and the quantity is a whole number from 1 to
    10,000; an accepted line with designators has their count as its quantity. BomNotes accepts
    exactly the texts whose trimmed and collapsed form is 1 to 500 characters, blank text
    reading as no note, and the value it keeps has no whitespace at its ends and no run of it
    inside, and is equal to itself built again from its own text.

    **Validates: Requirements 4.3, 4.4, 4.5**
    """
    count = len(designators)
    if count:
        allowed = quantity is None or quantity == count
    else:
        allowed = quantity is not None and 1 <= quantity <= MAX_LINE_QUANTITY
    try:
        content = LineContent.of(RESISTOR, designators, quantity, None)
    except ProjectsError:
        assert not allowed
    else:
        assert allowed
        assert content.quantity.value == (count or quantity)

    collapsed = " ".join(notes.split())
    try:
        kept = BomNotes(notes)
    except InvalidBomNotesError:
        assert not 1 <= len(collapsed) <= MAX_NOTES_LENGTH
    else:
        assert 1 <= len(collapsed) <= MAX_NOTES_LENGTH
        assert kept.value == collapsed
        assert kept.value.split(" ") == kept.value.split()
        assert BomNotes(kept.value) == kept


# --- Property 6: a BOM keeps its invariants under any edits --------------------------------


@dataclass(frozen=True)
class _Add:
    content: LineContent


@dataclass(frozen=True)
class _Replace:
    index: int
    content: LineContent


@dataclass(frozen=True)
class _Remove:
    index: int


type _Step = _Add | _Replace | _Remove

_steps = st.lists(
    st.one_of(
        st.builds(_Add, line_contents()),
        st.builds(_Replace, st.integers(0, 20), line_contents()),
        st.builds(_Remove, st.integers(0, 20)),
    ),
    max_size=25,
)


@dataclass(frozen=True)
class _ModelLine:
    id: BomLineId
    part_id: PartId
    designators: frozenset[Designator]


class _Model:
    """The BOM as a plain list of lines and their designator sets, run beside the real one."""

    def __init__(self) -> None:
        self.revision = a_revision()
        self.bom = BillOfMaterials(self.revision.id)
        self.lines: list[_ModelLine] = []

    def apply(self, step: _Step, minutes: int) -> None:
        match step:
            case _Add(content):
                when = NOW + timedelta(minutes=minutes)
                line = BomLine.on(self.revision, BomLineId(uuid7()), content, when)
                self._change(self.bom.with_line, line, at=len(self.lines))
            case _Replace(index, content) if self.lines:
                at = index % len(self.lines)
                self._change(
                    self.bom.replacing, self.bom.line(self.lines[at].id).revised(content), at
                )
            case _Remove(index) if self.lines:
                held = self.lines.pop(index % len(self.lines))
                self.bom = self.bom.without(held.id)

    def _change(self, change: Callable[[BomLine], BillOfMaterials], line: BomLine, at: int) -> None:
        holders = {
            designator: held.id
            for held in self.lines
            if held.id != line.id
            for designator in held.designators
        }
        if any(designator in holders for designator in line.content.designators):
            with pytest.raises(DesignatorTakenError) as refused:
                change(line)
            named = Designator.parse(refused.value.item or "")
            assert named in line.content.designators
            assert holders[named] == refused.value.line_id
            return
        self.bom = change(line)
        entry = _ModelLine(line.id, line.content.part_id, frozenset(line.content.designators))
        if at == len(self.lines):
            self.lines.append(entry)
        else:
            self.lines[at] = entry


@given(steps=_steps)
def test_a_bom_keeps_its_invariants_under_any_edits(steps: list[_Step]) -> None:
    """Property 6: a BOM keeps its invariants under any edits.

    For any sequence of adds, replacements and removals applied to one BillOfMaterials, with
    parts drawn from a small pool so that lines share parts and designators drawn so that they
    often clash, every step agrees with a model that is a plain list of lines and their
    designator sets. An add is refused exactly when one of its designators is held by another
    line, naming such a designator and the line holding it, and otherwise lands after every
    other line. A replacement is refused exactly when one of its new designators is held by
    another line, never for one of its own, and otherwise keeps its line's place. A removal
    frees its designators for later lines. After every step, no designator is on two lines,
    lines naming the same part are all kept, and the lines are in the order they were added.

    **Validates: Requirements 4.1, 4.6, 4.8, 4.9, 4.10**
    """
    model = _Model()
    for minutes, step in enumerate(steps):
        model.apply(step, minutes)
        lines = model.bom.lines
        assert [line.id for line in lines] == [held.id for held in model.lines]
        assert [line.content.part_id for line in lines] == [held.part_id for held in model.lines]
        assert [frozenset(line.content.designators) for line in lines] == [
            held.designators for held in model.lines
        ]
        named = [designator for line in lines for designator in line.content.designators]
        assert len(named) == len(set(named))
