"""The bills of materials that name a part, as catalog's deletion guard hears of them.

Plain values in catalog's own words: projects answers them through bootstrap (09's decision
13), and they live in the domain so that `PartInUseError` can carry them without the domain
importing the application.
"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PartUse:
    """A BOM that names a part: its project and revision, as the refusal names them."""

    project_id: UUID
    project_name: str
    revision_id: UUID
    revision_label: str


@dataclass(frozen=True, slots=True)
class PartUsage:
    """The first few BOMs naming a part, as many as were asked for, and how many in all."""

    uses: tuple[PartUse, ...]
    total: int  # every BOM of the workspace that names the part

    @property
    def more(self) -> int:
        """The BOMs beyond the ones named, which the refusal only counts."""
        return self.total - len(self.uses)
