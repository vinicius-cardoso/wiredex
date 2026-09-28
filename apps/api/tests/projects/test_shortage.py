from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta
from uuid import uuid7

from hypothesis import given
from hypothesis import strategies as st

from support.bom import (
    NOW,
    PART_POOL,
    a_line,
    a_revision,
    boms,
    catalogs,
    facts_of,
    stock_levels,
)
from wiredex.projects.domain.bom import BillOfMaterials, BomLine, LineQuantity, PartNeed
from wiredex.projects.domain.shortage import (
    PartFacts,
    PartShortage,
    ShortageReport,
    ShortageSummary,
    StockStatus,
)
from wiredex.projects.domain.values import BomLineId, PartId

RESISTOR, CAPACITOR, SENSOR, WIRE = PART_POOL


def _bom(*lines: tuple[PartId, str, int | None]) -> BillOfMaterials:
    revision = a_revision()
    return BillOfMaterials(
        revision.id,
        tuple(
            a_line(revision, part, designators, quantity, minutes=minutes)
            for minutes, (part, designators, quantity) in enumerate(lines)
        ),
    )


def test_a_part_the_stock_covers_is_covered() -> None:
    report = ShortageReport.of(
        _bom((RESISTOR, "R1-4", None)), {RESISTOR: facts_of(RESISTOR)}, {RESISTOR: 180}
    )

    assert report.parts == (
        PartShortage(PartNeed(RESISTOR, 4, 1), facts_of(RESISTOR), 180, 0, StockStatus.COVERED),
    )
    assert report.summary.complete


def test_a_part_with_too_little_stock_is_short_by_the_difference() -> None:
    report = ShortageReport.of(
        _bom((SENSOR, "U1, U2", None)), {SENSOR: facts_of(SENSOR)}, {SENSOR: 1}
    )

    (sensor,) = report.parts
    assert (sensor.available, sensor.short, sensor.status) == (1, 1, StockStatus.SHORT)
    assert not report.summary.complete


def test_a_part_no_lot_holds_has_none_available() -> None:
    report = ShortageReport.of(_bom((SENSOR, "U1", None)), {SENSOR: facts_of(SENSOR)}, {})

    (sensor,) = report.parts
    assert (sensor.available, sensor.short, sensor.status) == (0, 1, StockStatus.SHORT)


def test_a_consumable_holding_a_lot_is_never_counted() -> None:
    wire = facts_of(WIRE, "Hook-up wire 22 AWG", not_stocked=True)

    report = ShortageReport.of(_bom((WIRE, "", 3)), {WIRE: wire}, {WIRE: 1})

    (line,) = report.parts
    assert (line.part, line.available, line.short) == (wire, None, 0)
    assert line.status is StockStatus.NOT_STOCKED
    assert report.summary.not_stocked_parts == 1
    assert report.summary.complete


def test_a_part_the_catalog_no_longer_holds_is_unknown() -> None:
    report = ShortageReport.of(_bom((SENSOR, "U1", None)), {}, {SENSOR: 5})

    (sensor,) = report.parts
    assert (sensor.part, sensor.available, sensor.short) == (None, None, 0)
    assert sensor.status is StockStatus.UNKNOWN_PART
    assert report.summary.unknown_parts == 1
    assert not report.summary.complete


def test_a_part_both_tracked_and_not_stocked_is_not_stocked() -> None:
    board = facts_of(SENSOR, "ESP32-DevKitC", tracked=True, not_stocked=True)

    report = ShortageReport.of(_bom((SENSOR, "U1", None)), {SENSOR: board}, {})

    assert report.parts[0].status is StockStatus.NOT_STOCKED


def test_a_need_sums_across_two_lines_of_one_part() -> None:
    bom = _bom((RESISTOR, "R1, R2", None), (CAPACITOR, "C1", None), (RESISTOR, "R3-5", None))

    report = ShortageReport.of(bom, {part: facts_of(part) for part in PART_POOL}, {RESISTOR: 4})

    resistor, capacitor = report.parts
    assert resistor.need == PartNeed(RESISTOR, 5, 2)
    assert (resistor.short, capacitor.short) == (1, 1)
    assert report.summary == ShortageSummary(
        lines=3, parts=2, short_parts=2, short_pieces=2, not_stocked_parts=0, unknown_parts=0
    )


def test_an_empty_bom_is_complete() -> None:
    report = ShortageReport.of(BillOfMaterials(a_revision().id), {}, {})

    assert report.parts == ()
    assert report.summary == ShortageSummary(0, 0, 0, 0, 0, 0)
    assert report.summary.complete


# --- Property 7: the report adds up ---------------------------------------------------------


@given(bom=boms(), facts=catalogs(), available=stock_levels())
def test_the_report_adds_up(
    bom: BillOfMaterials, facts: dict[PartId, PartFacts], available: dict[PartId, int]
) -> None:
    """Property 7: the report adds up.

    For any BOM, any part facts that leave some of its parts out and mark some not stocked or
    tracked, and any available stock, ShortageReport.of lists each part the BOM names exactly
    once, in the order it first appears, with the number of lines naming it and their summed
    quantities as its need. A part without facts is unknown_part, with no facts, no available
    stock and none short. A not-stocked part is not_stocked, with no available stock and none
    short, whatever stock is given for it. Any other part has the stock given for it, or zero,
    as its available stock, max(0, need - available) short, and is short exactly when that is
    positive. The summary's counts are the sums over the parts, and the BOM is complete exactly
    when no part is short and none is unknown.

    **Validates: Requirements 6.1, 6.2, 6.4, 6.5, 6.6**
    """
    report = ShortageReport.of(bom, facts, available)

    first_seen = list(dict.fromkeys(line.content.part_id for line in bom.lines))
    assert [part.part_id for part in report.parts] == first_seen
    for part in report.parts:
        naming = [line for line in bom.lines if line.content.part_id == part.part_id]
        assert part.need.lines == len(naming)
        assert part.need.quantity == sum(line.content.quantity.value for line in naming)
        _check_part(part, facts.get(part.part_id), available.get(part.part_id, 0))

    summary = report.summary
    assert summary.lines == len(bom.lines)
    assert summary.parts == len(report.parts)
    assert summary.short_pieces == sum(part.short for part in report.parts)
    for status, count in (
        (StockStatus.SHORT, summary.short_parts),
        (StockStatus.NOT_STOCKED, summary.not_stocked_parts),
        (StockStatus.UNKNOWN_PART, summary.unknown_parts),
    ):
        assert count == sum(1 for part in report.parts if part.status is status)
    assert summary.complete == (summary.short_parts == 0 and summary.unknown_parts == 0)


def _check_part(part: PartShortage, facts: PartFacts | None, stock: int) -> None:
    if facts is None:
        assert (part.part, part.available, part.short) == (None, None, 0)
        assert part.status is StockStatus.UNKNOWN_PART
    elif facts.not_stocked:
        assert (part.part, part.available, part.short) == (facts, None, 0)
        assert part.status is StockStatus.NOT_STOCKED
    else:
        assert (part.part, part.available) == (facts, stock)
        assert part.short == max(0, part.need.quantity - stock)
        assert (part.status is StockStatus.SHORT) == (part.short > 0)
        assert part.status in {StockStatus.SHORT, StockStatus.COVERED}


# --- Property 8: the report ignores order and splits ----------------------------------------


def _split(lines: Sequence[BomLine], cuts: Sequence[int]) -> tuple[BomLine, ...]:
    """Each designator-free line of two or more pieces cut in two, the first part keeping
    `cut` pieces (at least one, and one fewer than the line): the same need, more lines."""
    split: list[BomLine] = []
    for index, line in enumerate(lines):
        quantity = line.content.quantity.value
        if line.content.designators or quantity < 2:
            split.append(line)
            continue
        kept = 1 + cuts[index % len(cuts)] % (quantity - 1)
        split.append(line.revised(replace(line.content, quantity=LineQuantity(kept))))
        rest = replace(line.content, quantity=LineQuantity(quantity - kept))
        split.append(
            BomLine(
                BomLineId(uuid7()),
                line.workspace_id,
                line.revision_id,
                rest,
                NOW + timedelta(days=1),
            )
        )
    return tuple(split)


def _by_part(report: ShortageReport) -> dict[PartId, tuple[int, int | None, int, StockStatus]]:
    return {
        part.part_id: (part.need.quantity, part.available, part.short, part.status)
        for part in report.parts
    }


@given(
    bom=boms(),
    facts=catalogs(),
    available=stock_levels(),
    cuts=st.lists(st.integers(0, 10_000), min_size=1, max_size=4),
    data=st.data(),
)
def test_the_report_ignores_order_and_splits(
    bom: BillOfMaterials,
    facts: dict[PartId, PartFacts],
    available: dict[PartId, int],
    cuts: list[int],
    data: st.DataObject,
) -> None:
    """Property 8: the report ignores order and splits.

    For any BOM, facts and stock, reordering its lines, or splitting a designator-free line's
    quantity across several lines of the same part and merging such lines back, gives a report
    with the same need, available stock, shortage and status for every part, and the same
    summary but for its count of lines.

    **Validates: Requirements 6.8**
    """
    report = ShortageReport.of(bom, facts, available)
    reordered = replace(bom, lines=tuple(data.draw(st.permutations(bom.lines))))
    split = replace(bom, lines=_split(data.draw(st.permutations(bom.lines)), cuts))

    for other in (reordered, split):
        again = ShortageReport.of(other, facts, available)
        assert _by_part(again) == _by_part(report)
        assert replace(again.summary, lines=0) == replace(report.summary, lines=0)
