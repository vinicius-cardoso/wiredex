"""`SearchWorkspace` over in-memory sources (19-command-palette).

The sources' own reads, and the hits bootstrap builds from each module's records, are the
integration tests' (`test_search_reads.py`); here is what the search does with them: which it
asks, in what order and for how many, and how their answers become groups.
"""

import pytest

from support.search import BENCH, Asked, sources
from wiredex.search.application.search import SearchWorkspace
from wiredex.search.domain.search import SearchKind, SearchText

pytestmark = pytest.mark.anyio


async def test_asks_every_source_in_turn_for_one_more_than_a_group_shows() -> None:
    # Decisions 3 and 4: one after the other, in the groups' order, each for limit + 1.
    held = sources()
    search = SearchWorkspace(list(held.values()))

    await search(BENCH, SearchText.of("  sensor "), 5)

    log = held[SearchKind.PART].log
    assert log == [Asked(kind, BENCH, "sensor", 6) for kind in SearchKind]


async def test_groups_the_hits_of_the_kinds_that_found_something() -> None:
    # Requirements 1.3 and 1.4.
    held = sources()
    parts = held[SearchKind.PART].hold("Sensor BME280", "Sensor SHT31", "Sensor DS18B20")
    (shelf,) = held[SearchKind.LOCATION].hold("Sensor shelf", detail="WX-L-0007")
    held[SearchKind.PROJECT].hold("Weather station")
    search = SearchWorkspace(list(held.values()))

    found = await search(BENCH, SearchText.of("sensor"), 2)

    assert found.text == "sensor"
    assert [(one.kind, len(one.hits), one.more) for one in found.groups] == [
        (SearchKind.PART, 2, True),
        (SearchKind.LOCATION, 1, False),
    ]
    assert found.groups[0].hits == tuple(parts[:2])
    assert found.groups[1].hits == (shelf,)


async def test_nothing_found_answers_no_group() -> None:
    held = sources()
    held[SearchKind.PART].hold("Resistor 4k7")
    search = SearchWorkspace(list(held.values()))

    found = await search(BENCH, SearchText.of("sensor"), 5)

    assert found.groups == ()
