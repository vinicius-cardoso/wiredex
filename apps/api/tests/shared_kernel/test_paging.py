"""A numbered page of a list: its bounds, where it starts, and the last page past the end."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.shared_kernel.domain.paging import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE,
    MAX_PAGE_SIZE,
    InvalidPageError,
    Page,
    PageRequest,
)


def test_a_request_is_the_first_page_of_50_unless_asked() -> None:
    assert PageRequest() == PageRequest(1, DEFAULT_PAGE_SIZE)
    assert DEFAULT_PAGE_SIZE == 50


@pytest.mark.parametrize(
    ("number", "size"), [(1, 1), (MAX_PAGE, 1), (1, MAX_PAGE_SIZE), (MAX_PAGE, MAX_PAGE_SIZE)]
)
def test_a_request_at_its_bounds_is_taken(number: int, size: int) -> None:
    assert PageRequest(number, size).number == number


@pytest.mark.parametrize(
    ("number", "size"),
    [(0, 50), (-1, 50), (MAX_PAGE + 1, 50), (1, 0), (1, -5), (1, MAX_PAGE_SIZE + 1)],
)
def test_a_request_out_of_bounds_is_refused(number: int, size: int) -> None:
    with pytest.raises(InvalidPageError):
        PageRequest(number, size)


def test_a_refused_request_is_a_value_error() -> None:
    assert issubclass(InvalidPageError, ValueError)


def test_a_page_starts_after_the_pages_before_it_and_reaches_its_own_end() -> None:
    assert (PageRequest(1, 25).offset, PageRequest(1, 25).reach) == (0, 25)
    assert (PageRequest(3, 25).offset, PageRequest(3, 25).reach) == (50, 75)


def test_the_deepest_page_stays_inside_a_bigint() -> None:
    assert PageRequest(MAX_PAGE, MAX_PAGE_SIZE).reach < 2**63 - 1


@pytest.mark.parametrize(
    ("asked", "total", "served"),
    [
        (PageRequest(1, 50), 0, PageRequest(1, 50)),  # an empty list has one empty page
        (PageRequest(4, 50), 0, PageRequest(1, 50)),
        (PageRequest(2, 25), 50, PageRequest(2, 25)),  # an exact multiple: its last page is full
        (PageRequest(3, 25), 50, PageRequest(2, 25)),
        (PageRequest(3, 25), 51, PageRequest(3, 25)),  # one past it: a page of one
        (PageRequest(9, 25), 51, PageRequest(3, 25)),
        (PageRequest(2, 10), 312, PageRequest(2, 10)),  # inside the range, kept
    ],
)
def test_a_request_past_the_end_is_served_as_the_last_page(
    asked: PageRequest, total: int, served: PageRequest
) -> None:
    assert asked.within(total) == served


@given(
    st.integers(min_value=1, max_value=MAX_PAGE),
    st.integers(min_value=1, max_value=MAX_PAGE_SIZE),
    st.integers(min_value=0, max_value=10**7),
)
def test_the_page_served_holds_something_unless_the_list_is_empty(
    number: int, size: int, total: int
) -> None:
    served = PageRequest(number, size).within(total)
    assert served.size == size
    assert served.number <= number
    if total == 0:
        assert served.number == 1
    else:
        assert served.offset < total


def test_a_page_holds_its_items_the_total_and_the_request_served() -> None:
    page = Page(("a", "b"), 7, PageRequest(4, 2))
    assert (page.items, page.total, page.request.number) == (("a", "b"), 7, 4)
