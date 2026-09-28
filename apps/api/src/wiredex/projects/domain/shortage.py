"""What a revision's BOM is short of, against the catalog and the stock as they stand now.

A pure function of three values: the BOM, what the catalog says about its parts and what is
available of them. Nothing here is stored (decision 10), so a receipt, a rename or a flag
change is right at the next read with nothing to invalidate. 10's reserve and the `v0.8.0`
dashboard read the same report.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from wiredex.projects.domain.bom import BillOfMaterials, PartNeed
from wiredex.projects.domain.values import PartId


@dataclass(frozen=True, slots=True)
class PartFacts:
    """What the catalog says about a part a BOM names, in projects' own words."""

    part_id: PartId
    name: str
    manufacturer: str | None
    mpn: str | None
    package: str | None
    tracked_individually: bool
    not_stocked: bool


class StockStatus(StrEnum):
    COVERED = "covered"  # the available stock covers the need
    SHORT = "short"
    NOT_STOCKED = "not_stocked"  # a consumable: never short (decision 3)
    UNKNOWN_PART = "unknown_part"  # the catalog no longer holds it (decision 13)


@dataclass(frozen=True, slots=True)
class PartShortage:
    """One part of the BOM: what it needs, what there is, and how many are missing."""

    need: PartNeed
    part: PartFacts | None  # None: an unknown part
    available: int | None  # None for a consumable and for an unknown part
    short: int  # the need less the available stock when positive, else 0
    status: StockStatus

    @classmethod
    def of(cls, need: PartNeed, part: PartFacts | None, available: int) -> PartShortage:
        if part is None:
            return cls(need, None, None, 0, StockStatus.UNKNOWN_PART)
        if part.not_stocked:
            # Whatever a lot held before the flag was set, a consumable is never counted.
            return cls(need, part, None, 0, StockStatus.NOT_STOCKED)
        short = max(0, need.quantity - available)
        status = StockStatus.SHORT if short else StockStatus.COVERED
        return cls(need, part, available, short, status)

    @property
    def part_id(self) -> PartId:
        return self.need.part_id


@dataclass(frozen=True, slots=True)
class ShortageSummary:
    lines: int
    parts: int
    short_parts: int
    short_pieces: int
    not_stocked_parts: int
    unknown_parts: int

    @property
    def complete(self) -> bool:
        """No part short and none unknown (requirement 6.6); a consumable doesn't count."""
        return self.short_parts == 0 and self.unknown_parts == 0


@dataclass(frozen=True, slots=True)
class ShortageReport:
    parts: tuple[PartShortage, ...]  # in the order `needs()` gives them
    summary: ShortageSummary

    @classmethod
    def of(
        cls,
        bom: BillOfMaterials,
        facts: Mapping[PartId, PartFacts],
        available: Mapping[PartId, int],
    ) -> ShortageReport:
        """Decision 10 and nothing else: a part absent from `facts` is unknown, a consumable
        is never short, and any other part has `available.get(part_id, 0)`."""
        parts = tuple(
            PartShortage.of(need, facts.get(need.part_id), available.get(need.part_id, 0))
            for need in bom.needs()
        )
        return cls(parts, _summary(len(bom.lines), parts))


def _summary(lines: int, parts: tuple[PartShortage, ...]) -> ShortageSummary:
    def counting(status: StockStatus) -> int:
        return sum(1 for part in parts if part.status is status)

    return ShortageSummary(
        lines=lines,
        parts=len(parts),
        short_parts=counting(StockStatus.SHORT),
        short_pieces=sum(part.short for part in parts),
        not_stocked_parts=counting(StockStatus.NOT_STOCKED),
        unknown_parts=counting(StockStatus.UNKNOWN_PART),
    )
