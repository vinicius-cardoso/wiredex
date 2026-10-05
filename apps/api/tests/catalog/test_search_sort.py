"""The sort a search is ordered by: `PartSort` refuses a shape that contradicts itself (an
attribute sort with no key, a name sort carrying one)."""

import pytest

from wiredex.catalog.domain.errors import InvalidSortError
from wiredex.catalog.domain.search import PartSort, SortDirection, SortField
from wiredex.catalog.domain.values import AttributeKey

RESISTANCE = AttributeKey("resistance")


def test_part_sort_defaults_to_newest_descending() -> None:
    sort = PartSort.newest()

    assert sort.field is SortField.NEWEST
    assert sort.direction is SortDirection.DESC
    assert sort.key is None


def test_part_sort_by_name_defaults_to_ascending() -> None:
    sort = PartSort.by_name()

    assert sort.field is SortField.NAME
    assert sort.direction is SortDirection.ASC
    assert sort.key is None


def test_part_sort_by_attribute_carries_its_key() -> None:
    sort = PartSort.by_attribute(RESISTANCE, SortDirection.DESC)

    assert sort.field is SortField.ATTRIBUTE
    assert sort.direction is SortDirection.DESC
    assert sort.key == RESISTANCE


def test_part_sort_refuses_an_attribute_sort_without_a_key() -> None:
    with pytest.raises(InvalidSortError):
        PartSort(SortField.ATTRIBUTE)


@pytest.mark.parametrize("field", [SortField.NEWEST, SortField.NAME])
def test_part_sort_refuses_a_non_attribute_sort_carrying_a_key(field: SortField) -> None:
    with pytest.raises(InvalidSortError):
        PartSort(field, key=RESISTANCE)
