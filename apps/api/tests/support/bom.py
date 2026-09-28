"""Hypothesis strategies for designators and the lists of them, shared by the BOM tests.

Sets are drawn as runs of consecutive numbers under a handful of prefixes, because runs are
what ranges and the canonical text are about: independent numbers would almost never sit next
to each other, and every property about ranges would go untested.
"""

import string
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from hypothesis import strategies as st

from wiredex.projects.domain.designators import (
    MAX_DESIGNATOR_LETTERS,
    MAX_DESIGNATOR_NUMBER,
    MAX_DESIGNATORS,
    Designator,
)

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
