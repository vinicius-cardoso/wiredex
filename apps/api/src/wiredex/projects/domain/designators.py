"""Reference designators, and the lists of them a BOM line holds (decisions 5 and 6).

A designator names one physical part's place on a build: `R1`, `C12`, `SW1`. A list is typed
the way a schematic writes it, `R1-4, R7`, and written back in one canonical form, `R1–R4,
R7`, that reads back as the same designators. 11's pin references (`U1.21`) split at the dot,
which is why no designator may hold one.
"""

import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import groupby

from wiredex.projects.domain.errors import (
    InvalidDesignatorError,
    InvalidDesignatorRangeError,
    RepeatedDesignatorError,
    TooManyDesignatorsError,
)

MAX_DESIGNATOR_LETTERS = 8
MAX_DESIGNATOR_NUMBER = 9_999
MAX_DESIGNATORS = 256  # on one line

# Explicit ASCII classes: `\d` and `\w` would take other scripts' digits and letters, which
# NFKC doesn't fold, and the sort and the database CHECK are ASCII.
_DESIGNATOR = re.compile(r"([A-Za-z]+)([0-9]+)")
_STORED_LETTERS = re.compile(rf"[A-Z]{{1,{MAX_DESIGNATOR_LETTERS}}}")
_DIGITS = re.compile(r"[0-9]+")
_DASHES = "-–—"
_AROUND_A_DASH = re.compile(rf"\s*([{_DASHES}])\s*")
_SEPARATORS = re.compile(r"[,\s]+")
# Three designators in a row are the shortest run worth a range: `R1, R2` is no longer than
# `R1–R2`, and reads plainer (requirement 3.7).
_SHORTEST_RANGE = 3
_RANGE_ENDS = 2


@dataclass(frozen=True, slots=True, order=True)
class Designator:
    """A reference designator: letters, then a number (decision 5). Ordered by its letters
    and then its number, which is the canonical order: C1 < R1 < R2 < R10 < RN1."""

    letters: str  # 1-8 ASCII capitals
    number: int  # 1-9999

    def __post_init__(self) -> None:
        letters_fit = _STORED_LETTERS.fullmatch(self.letters) is not None
        if not (letters_fit and 1 <= self.number <= MAX_DESIGNATOR_NUMBER):
            raise _not_a_designator(f"{self.letters}{self.number}")

    @classmethod
    def parse(cls, text: str) -> Designator:
        """NFKC, trimmed, then letters and digits whose number is from 1 to 9999; the letters
        upper-cased, leading zeros dropped, so `r01`, `R1` and a fullwidth R1 are one
        designator."""
        item = unicodedata.normalize("NFKC", text).strip()
        read = _DESIGNATOR.fullmatch(item)
        if read is None:
            raise _not_a_designator(item)
        letters, digits = read.groups()
        return _designator(item, letters.upper(), digits)

    def __str__(self) -> str:
        return f"{self.letters}{self.number}"


@dataclass(frozen=True, slots=True)
class Designators:
    """A line's designators: each once, in canonical order, at most 256."""

    values: tuple[Designator, ...]

    def __post_init__(self) -> None:
        # Checked here rather than only in `of`, so no path holds a designator twice or out of
        # order, and two spellings of one list compare equal.
        seen: set[Designator] = set()
        for designator in self.values:
            if designator in seen:
                raise _named_twice(designator)
            seen.add(designator)
        if len(seen) > MAX_DESIGNATORS:
            raise _too_many()
        object.__setattr__(self, "values", tuple(sorted(seen)))

    @classmethod
    def parse(cls, text: str) -> Designators:
        """A list as typed (decision 6). Blank text is no designators."""
        normalized = unicodedata.normalize("NFKC", text)
        closed_up = _AROUND_A_DASH.sub(r"\1", normalized)
        reading = _Reading()
        for item in _SEPARATORS.split(closed_up):
            if item:
                reading.read(item)
        return cls(tuple(reading.designators))

    @classmethod
    def of(cls, designators: Iterable[Designator]) -> Designators:
        """Sorted; a repeat is `RepeatedDesignatorError` naming it, and more than 256 is
        `TooManyDesignatorsError`."""
        return cls(tuple(designators))

    @classmethod
    def none(cls) -> Designators:
        return cls(())

    def text(self) -> str:
        """The canonical text: `C1, R1–R3, R7` (requirement 3.7)."""
        items: list[str] = []
        for _, prefixed in groupby(self.values, key=lambda designator: designator.letters):
            for run in _runs(list(prefixed)):
                if len(run) >= _SHORTEST_RANGE:
                    items.append(f"{run[0]}–{run[-1]}")
                else:
                    items.extend(str(designator) for designator in run)
        return ", ".join(items)

    def __len__(self) -> int:
        return len(self.values)

    def __iter__(self) -> Iterator[Designator]:
        return iter(self.values)

    def __contains__(self, designator: object) -> bool:
        return designator in self.values


class _Reading:
    """The designators a list has named so far, in the order it named them.

    Each range is checked against them before it is expanded, so `R1–R9999` is refused as too
    many without building 9,999 values, and a repeat is named as soon as it is met.
    """

    def __init__(self) -> None:
        self.designators: list[Designator] = []
        self._seen: set[Designator] = set()

    def read(self, item: str) -> None:
        ends = re.split(f"[{_DASHES}]", item)
        if len(ends) == 1:
            self._name([Designator.parse(item)])
            return
        if len(ends) != _RANGE_ENDS or not all(ends):
            raise _not_a_designator(item)
        start = Designator.parse(ends[0])
        end = _range_end(item, start, ends[1])
        self._name_range(item, start, end)

    def _name_range(self, item: str, start: Designator, end: Designator) -> None:
        if end.letters != start.letters:
            raise InvalidDesignatorRangeError(
                f"the range {item} has to keep to one prefix, as R1–R4 does", item=item
            )
        if end.number <= start.number:
            raise InvalidDesignatorRangeError(
                f"the range {item} has to run upwards, as R1–R4 does", item=item
            )
        numbers = range(start.number, end.number + 1)
        for designator in sorted(self._seen):
            if designator.letters == start.letters and designator.number in numbers:
                raise _named_twice(designator)
        if len(self._seen) + len(numbers) > MAX_DESIGNATORS:
            raise _too_many()
        self._name([Designator(start.letters, number) for number in numbers])

    def _name(self, designators: list[Designator]) -> None:
        for designator in designators:
            if designator in self._seen:
                raise _named_twice(designator)
            self._seen.add(designator)
            self.designators.append(designator)
        if len(self._seen) > MAX_DESIGNATORS:
            raise _too_many()


def _range_end(item: str, start: Designator, text: str) -> Designator:
    """A range's second end: a designator, or a bare number taking the start's letters."""
    if _DIGITS.fullmatch(text):
        # Named as the whole range: `R1-0` is a range whose end isn't a designator.
        return _designator(item, start.letters, text)
    try:
        return Designator.parse(text)
    except InvalidDesignatorError as error:
        raise _not_a_designator(item) from error


def _designator(item: str, letters: str, digits: str) -> Designator:
    """The designator, or a refusal naming the item as it was typed rather than as it would
    have been stored."""
    # Leading zeros are dropped, so only what is left can be too long; checked before int(),
    # which refuses a string of thousands of digits with an error of its own.
    significant = digits.lstrip("0") or "0"
    if len(significant) > len(str(MAX_DESIGNATOR_NUMBER)):
        raise _not_a_designator(item)
    try:
        return Designator(letters, int(significant))
    except InvalidDesignatorError as error:
        raise _not_a_designator(item) from error


def _runs(designators: list[Designator]) -> Iterator[list[Designator]]:
    """Maximal runs of consecutive numbers among designators of one prefix, in order."""
    run: list[Designator] = []
    for designator in designators:
        if run and designator.number != run[-1].number + 1:
            yield run
            run = []
        run.append(designator)
    if run:
        yield run


def _not_a_designator(item: str) -> InvalidDesignatorError:
    return InvalidDesignatorError(
        f"{item!r} is not a designator like R1 or C12: 1 to {MAX_DESIGNATOR_LETTERS} letters, "
        f"then a number from 1 to {MAX_DESIGNATOR_NUMBER:,}",
        item=item,
    )


def _named_twice(designator: Designator) -> RepeatedDesignatorError:
    return RepeatedDesignatorError(f"{designator} is named twice", item=str(designator))


def _too_many() -> TooManyDesignatorsError:
    return TooManyDesignatorsError(f"a line holds at most {MAX_DESIGNATORS} designators")
