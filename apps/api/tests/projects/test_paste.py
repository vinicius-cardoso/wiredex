"""Pasting wiring: several lines as one change to a netlist, over the in-memory fakes.

The bench is `test_netlist_use_cases`' weather station: an ESP32 with a pinout on U1, a BME280
with one on U2, and a resistor without one on R1 and R2.
"""

import pytest

from support.wiring_bench import Bench
from wiredex.projects.domain.errors import (
    JoinsTwoNetsError,
    NamedOtherwiseError,
    NoPinsError,
    RevisionContentLockedError,
    TooManyRowsError,
    UnknownDesignatorError,
)
from wiredex.projects.domain.netlist import WireColor
from wiredex.projects.domain.paste import MAX_PASTED_ROWS, PastedRow
from wiredex.projects.domain.values import RevisionStatus

pytestmark = pytest.mark.anyio


async def paste(bench: Bench, *rows: PastedRow) -> dict[str, tuple[str, WireColor | None]]:
    """The netlist after the paste: each net's pins as text, and its colour, by name."""
    view = await bench.world.paste_nets(bench.revision.workspace_id, bench.revision.id, rows)
    return {
        str(net.content.name): (net.content.pins.text(), net.content.color)
        for net in view.netlist.nets
    }


async def test_a_named_line_makes_a_net_with_its_pins_and_colour() -> None:
    bench = Bench()

    nets = await paste(
        bench,
        PastedRow("U1.25, U2.3, R1.2", name="SDA", color="blue"),
        PastedRow("U1.22 U2.SCL", name="SCL"),
    )

    assert nets == {
        "SDA": ("R1.2, U1.25, U2.3", WireColor.BLUE),
        "SCL": ("U1.22, U2.4", None),
    }
    assert bench.world.work.commits == 1


async def test_a_line_with_no_name_is_named_after_one_of_its_pins() -> None:
    # The role a pin was typed by; else the label its pinout gives it; else the two ends.
    bench = Bench()

    nets = await paste(
        bench,
        PastedRow("U1.25, U2.sda"),
        PastedRow("U1.22, U2.4"),
        PastedRow("R1.1, R2.1"),
    )

    assert nets == {
        "SDA": ("U1.25, U2.3", None),
        "GPIO22": ("U1.22, U2.4", None),
        "R1.1-R2.1": ("R1.1, R2.1", None),
    }


async def test_a_pin_already_on_a_net_takes_the_lines_other_pins_there() -> None:
    # Connecting to a pin is joining its net, which is what keeps a pin off two nets.
    bench = Bench()
    await bench.add("GND", "U1.14", "black")
    commits = bench.world.work.commits

    nets = await paste(bench, PastedRow("U1.14, R1.1"), PastedRow("R1.1, R2.1", color="red"))

    # The second line joins through the pin the first just added, and never repaints the net.
    assert nets == {"GND": ("R1.1, R2.1, U1.14", WireColor.BLACK)}
    assert bench.world.work.commits == commits + 1


async def test_a_name_a_net_already_has_takes_the_lines_pins_to_it() -> None:
    bench = Bench()
    await bench.add("SDA", "U1.25")

    nets = await paste(bench, PastedRow("U2.3", name="sda", color="blue"), PastedRow("U2.sda"))

    # Case aside, as a net's name is unique; a net with no colour takes the line's; and a line
    # named after its pin's role finds the net of that name.
    assert nets == {"SDA": ("U1.25, U2.3", WireColor.BLUE)}


async def test_a_line_that_changes_nothing_writes_nothing() -> None:
    bench = Bench()
    await bench.add("SDA", "U1.25, U2.3")
    commits = bench.world.work.commits

    nets = await paste(bench, PastedRow("U2.3, U1.25, U1.25", name="SDA"))

    assert nets == {"SDA": ("U1.25, U2.3", None)}
    assert bench.world.work.commits == commits


async def test_a_line_cant_join_two_nets_and_the_whole_paste_is_refused() -> None:
    bench = Bench()
    await bench.add("GND", "U1.14")
    await bench.add("SHIELD", "R2.1")
    commits = bench.world.work.commits

    with pytest.raises(
        JoinsTwoNetsError, match=r"U1\.14 is on GND and R2\.1 on SHIELD: one line can't join"
    ) as refused:
        await paste(bench, PastedRow("U1.25, U2.3", name="SDA"), PastedRow("U1.14, R2.1"))

    # The second line, and nothing of the first was kept.
    assert refused.value.row == 2
    assert bench.world.work.commits == commits
    assert len(bench.world.work.nets.saved) == 2


async def test_a_line_cant_name_a_net_while_its_pin_is_on_another() -> None:
    bench = Bench()
    await bench.add("GND", "U1.14")

    with pytest.raises(
        NamedOtherwiseError, match=r"U1\.14 is already on GND, and this line names VSS"
    ) as refused:
        await paste(bench, PastedRow("U1.14, R1.1", name="VSS"))
    assert (refused.value.row, refused.value.item) == (1, "U1.14")

    # Named as the net it is on, the same line joins it.
    assert await paste(bench, PastedRow("U1.14, R1.1", name="gnd")) == {
        "GND": ("R1.1, U1.14", None)
    }


async def test_a_refused_reference_names_its_line() -> None:
    bench = Bench()

    with pytest.raises(UnknownDesignatorError) as refused:
        await paste(bench, PastedRow("U1.25, U2.3"), PastedRow("U1.22, U9.1", name="SCL"))
    assert (refused.value.row, refused.value.item) == (2, "U9.1")

    with pytest.raises(NoPinsError) as empty:
        await paste(bench, PastedRow("  ", name="SDA"))
    assert empty.value.row == 1


async def test_only_a_drafts_wiring_takes_a_paste_and_a_paste_has_a_limit() -> None:
    with pytest.raises(RevisionContentLockedError):
        await paste(Bench(RevisionStatus.BUILT), PastedRow("U1.25, U2.3"))

    with pytest.raises(TooManyRowsError):
        await paste(Bench(), *[PastedRow("U1.25")] * (MAX_PASTED_ROWS + 1))
