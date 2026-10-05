"""A numbered page of a list, in words every module's lists share.

A list is read a page at a time: which page and how many per page come in, and the page served
goes out with how many the whole list holds, so a reader can jump to any page and see the total.
A page past the end is served as the last one, and says so.
"""

from dataclasses import dataclass
from math import ceil

# 50 per page unless asked, never more than 100.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100

# Far beyond any list one owner keeps, and it holds the offset well inside a bigint.
MAX_PAGE = 100_000


class InvalidPageError(ValueError):
    """A page number or size outside its bounds. The API's own bounds refuse these first."""


@dataclass(frozen=True, slots=True)
class PageRequest:
    """Which page, counted from 1, and how many per page."""

    number: int = 1
    size: int = DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        if not 1 <= self.number <= MAX_PAGE:
            raise InvalidPageError(f"a page is numbered from 1 to {MAX_PAGE}")
        if not 1 <= self.size <= MAX_PAGE_SIZE:
            raise InvalidPageError(f"a page holds from 1 to {MAX_PAGE_SIZE} items")

    @property
    def offset(self) -> int:
        """How many items the pages before this one hold."""
        return (self.number - 1) * self.size

    @property
    def reach(self) -> int:
        """How many items from the start this page needs read: its own and those before it."""
        return self.number * self.size

    def within(self, total: int) -> PageRequest:
        """This request, or the last page when it lies past the end of a list of `total`
        items; an empty list has one page, empty."""
        last = max(1, ceil(total / self.size))
        if self.number <= last:
            return self
        return PageRequest(last, self.size)


@dataclass(frozen=True, slots=True)
class Page[T]:
    """The items of the page served, how many the whole list holds, and which page it is."""

    items: tuple[T, ...]
    total: int
    request: PageRequest
