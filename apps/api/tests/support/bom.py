"""Hypothesis strategies for designators, the lists of them and BOMs, shared by the BOM
tests, and the revision a domain test hangs its lines from.

Sets are drawn as runs of consecutive numbers under a handful of prefixes, because runs are
what ranges and the canonical text are about: independent numbers would almost never sit next
to each other, and every property about ranges would go untested. BOM lines draw their parts
and designators from small pools, so that lines share parts and their designators clash.
"""

import string
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid7

from hypothesis import strategies as st

from wiredex.projects.domain.bom import (
    MAX_LINE_QUANTITY,
    BillOfMaterials,
    BomLine,
    BomNotes,
    LineContent,
    LineQuantity,
)
from wiredex.projects.domain.designators import (
    MAX_DESIGNATOR_LETTERS,
    MAX_DESIGNATOR_NUMBER,
    MAX_DESIGNATORS,
    Designator,
    Designators,
)
from wiredex.projects.domain.errors import DesignatorTakenError
from wiredex.projects.domain.project import Project, ProjectDetails
from wiredex.projects.domain.revision import Revision, RevisionDetails
from wiredex.projects.domain.shortage import PartFacts
from wiredex.projects.domain.values import (
    BomLineId,
    PartId,
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    RevisionStatus,
    WorkspaceId,
)

NOW = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())

# Prefixes a schematic uses, and RN beside R so one prefix is the start of another.
COMMON_PREFIXES = ("C", "D", "J", "Q", "R", "RN", "SW", "U")

prefixes = st.sampled_from(COMMON_PREFIXES) | st.text(
    alphabet=string.ascii_uppercase, min_size=1, max_size=MAX_DESIGNATOR_LETTERS
)
designators = st.builds(Designator, prefixes, st.integers(1, MAX_DESIGNATOR_NUMBER))

_DASHES = ("-", "–", "—")
_AROUND_A_DASH = ("", " ", "  ", "\t")
_SEPARATORS = (",", " ", ", ", " , ", ",\t", "\n", ",,", ",  ")
_LONGEST_RUN = 40


@st.composite
def designator_sets(
    draw: st.DrawFn, min_size: int = 0, max_size: int = MAX_DESIGNATORS
) -> frozenset[Designator]:
    """A set of distinct designators, built from runs under a few prefixes so that ranges of
    every length show up, and trimmed to its drawn size in canonical order."""
    size = draw(st.integers(min_size, max_size))
    chosen: set[Designator] = set()
    while len(chosen) < size:
        letters = draw(prefixes)
        start = draw(st.integers(1, MAX_DESIGNATOR_NUMBER))
        length = draw(st.integers(1, _LONGEST_RUN))
        end = min(start + length - 1, MAX_DESIGNATOR_NUMBER)
        chosen.update(Designator(letters, number) for number in range(start, end + 1))
    return frozenset(sorted(chosen)[:size])


def runs_of(wanted: Iterable[Designator]) -> Iterator[list[Designator]]:
    """The maximal runs of consecutive numbers under one prefix, in canonical order."""
    run: list[Designator] = []
    for designator in sorted(wanted):
        if run and (
            designator.letters != run[-1].letters or designator.number != run[-1].number + 1
        ):
            yield run
            run = []
        run.append(designator)
    if run:
        yield run


def _fullwidth(text: str) -> str:
    """ASCII letters and digits in their fullwidth forms, which NFKC folds back."""
    return "".join(chr(ord(char) + 0xFEE0) if char.isalnum() else char for char in text)


@dataclass(frozen=True, slots=True)
class Spelling:
    """How the owner might type a designator: any case, leading zeros, fullwidth forms."""

    case: Callable[[str], str]
    zeros: int
    fullwidth: bool

    def of(self, designator: Designator) -> str:
        text = self.case(designator.letters) + "0" * self.zeros + str(designator.number)
        return _fullwidth(text) if self.fullwidth else text


# Drawn once per piece of a list rather than per designator: a list of 256 would otherwise
# take a thousand draws, and the properties would spend their time generating.
spellings = st.builds(
    Spelling,
    st.sampled_from([str.upper, str.lower, str.swapcase]),
    st.integers(0, 2),
    st.booleans(),
)


def designator_spellings(designator: Designator) -> st.SearchStrategy[str]:
    return spellings.map(lambda spelling: spelling.of(designator))


@st.composite
def range_spellings(draw: st.DrawFn, start: Designator, end: Designator) -> str:
    """A range from start to end: any dash, spaced or not, the end in full or a bare number."""
    dash = draw(st.sampled_from(_DASHES))
    before = draw(st.sampled_from(_AROUND_A_DASH))
    after = draw(st.sampled_from(_AROUND_A_DASH))
    last = draw(designator_spellings(end))
    if draw(st.booleans()):
        last = str(end.number)
    return f"{draw(designator_spellings(start))}{before}{dash}{after}{last}"


@st.composite
def list_items(draw: st.DrawFn, wanted: Iterable[Designator]) -> list[str]:
    """The items of a list naming exactly the set: each run cut into pieces, a piece of two or
    more written as a range or one designator at a time, the items in any order."""
    items: list[str] = []
    for run in runs_of(wanted):
        position = 0
        while position < len(run):
            size = draw(st.integers(1, len(run) - position))
            piece = run[position : position + size]
            position += size
            if size > 1 and draw(st.booleans()):
                items.append(draw(range_spellings(piece[0], piece[-1])))
            else:
                spelling = draw(spellings)
                items.extend(spelling.of(designator) for designator in piece)
    return draw(st.permutations(items))


@st.composite
def joined(draw: st.DrawFn, items: list[str]) -> str:
    """Items separated by any mix of commas and whitespace, maybe some around the ends too.

    A few separators are drawn and taken in turn, rather than one drawn per item.
    """
    separators = draw(st.lists(st.sampled_from(_SEPARATORS), min_size=1, max_size=3))
    text = ""
    for index, item in enumerate(items):
        if index:
            text += separators[index % len(separators)]
        text += item
    edges = st.sampled_from(("", " ", ", "))
    return draw(edges) + text + draw(edges)


@st.composite
def list_spellings(draw: st.DrawFn, wanted: Iterable[Designator]) -> str:
    """Any way of writing a set of designators as one list (Property 4)."""
    return draw(joined(draw(list_items(wanted))))


# --- Revisions, lines and BOMs --------------------------------------------------------------


def a_revision(status: RevisionStatus = RevisionStatus.DRAFT, label: str = "A") -> Revision:
    """A revision of a fresh project in the bench, created at NOW."""
    project = Project.start(
        ProjectId(uuid7()), BENCH, ProjectDetails(ProjectName("Weather station")), NOW
    )
    revision = Revision.draft(
        RevisionId(uuid7()), project, RevisionDetails(RevisionLabel(label)), NOW
    )
    # Only 10-build-lifecycle moves a status; until then the tests place one.
    revision.status = status
    return revision


def a_line(
    revision: Revision,
    part_id: PartId,
    designators: str = "",
    quantity: int | None = None,
    *,
    minutes: int = 0,
) -> BomLine:
    """A line of the revision, its designators typed as the owner would."""
    content = LineContent.of(part_id, Designators.parse(designators), quantity, None)
    return BomLine.on(revision, BomLineId(uuid7()), content, NOW + timedelta(minutes=minutes))


# A handful of parts and a handful of designators, so lines share parts and clash often.
PART_POOL = tuple(PartId(uuid7()) for _ in range(4))
_DESIGNATOR_POOL = tuple(
    Designator(letters, number) for letters in ("C", "R") for number in range(1, 7)
)

part_ids = st.sampled_from(PART_POOL)
bom_notes = st.none() | st.builds(BomNotes, st.sampled_from(["I²C pull-ups", "about 2 m"]))


@st.composite
def line_contents(draw: st.DrawFn, parts: Sequence[PartId] = PART_POOL) -> LineContent:
    """A line's content: some designators from the pool and their count, or none and a
    quantity."""
    part_id = draw(st.sampled_from(parts))
    notes = draw(bom_notes)
    held = draw(st.sets(st.sampled_from(_DESIGNATOR_POOL), max_size=4))
    if held:
        designators = Designators.of(held)
        return LineContent(part_id, designators, LineQuantity(len(designators)), notes)
    quantity = draw(st.integers(1, MAX_LINE_QUANTITY) | st.integers(1, 5))
    return LineContent(part_id, Designators.none(), LineQuantity(quantity), notes)


@st.composite
def boms(
    draw: st.DrawFn, revision: Revision | None = None, parts: Sequence[PartId] = PART_POOL
) -> BillOfMaterials:
    """A BOM of the revision, built line by line through its own rules: a drawn line whose
    designators another line holds is left out, as the BOM would refuse it."""
    target = revision if revision is not None else a_revision()
    bom = BillOfMaterials(target.id)
    for minutes, content in enumerate(draw(st.lists(line_contents(parts), max_size=8))):
        line = BomLine.on(target, BomLineId(uuid7()), content, NOW + timedelta(minutes=minutes))
        try:
            bom = bom.with_line(line)
        except DesignatorTakenError:
            continue
    return bom


def facts_of(
    part_id: PartId,
    name: str = "Resistor 4k7 0805",
    *,
    tracked: bool = False,
    not_stocked: bool = False,
) -> PartFacts:
    """A part as the catalog describes it, with no manufacturer, part number or package."""
    return PartFacts(part_id, name, None, None, None, tracked, not_stocked)


@st.composite
def catalogs(draw: st.DrawFn, parts: Sequence[PartId] = PART_POOL) -> dict[PartId, PartFacts]:
    """What the catalog holds among the parts: some left out, some tracked, some not stocked,
    some both."""
    held: dict[PartId, PartFacts] = {}
    for part_id in parts:
        if draw(st.booleans()):
            held[part_id] = facts_of(
                part_id, tracked=draw(st.booleans()), not_stocked=draw(st.booleans())
            )
    return held


def stock_levels(parts: Sequence[PartId] = PART_POOL) -> st.SearchStrategy[dict[PartId, int]]:
    """What is available of the parts: some absent, which reads as none."""
    return st.dictionaries(st.sampled_from(parts), st.integers(0, 2 * MAX_LINE_QUANTITY))
