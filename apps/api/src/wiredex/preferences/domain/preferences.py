"""What a workspace has chosen about how Wiredex answers it (24-minimum-stock).

One row per workspace, created the first time a choice is saved: a workspace that never opened
its settings has the defaults, which `WorkspacePreferences.default` spells out.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType
from uuid import UUID

# Preferences declares its own WorkspaceId, as every module does: modules don't import each
# other's domain.
WorkspaceId = NewType("WorkspaceId", UUID)


class PreferencesError(ValueError):
    """A choice that isn't one of the options. The message is safe to show to users."""


class StockBasis(StrEnum):
    """What a part's minimum stock is compared against. `FREE` is what is on hand and not
    reserved for a build; `TOTAL` is everything on hand, reserved or not."""

    FREE = "free"
    TOTAL = "total"

    @classmethod
    def parse(cls, text: str) -> StockBasis:
        try:
            return cls(text)
        except ValueError as error:
            options = ", ".join(basis.value for basis in cls)
            raise PreferencesError(f"a stock basis is one of: {options}") from error


@dataclass(eq=False)
class WorkspacePreferences:
    workspace_id: WorkspaceId
    # Free unless the workspace says otherwise: parts promised to a build can't be used for
    # the next one, so they shouldn't hide a part that is running out.
    stock_basis: StockBasis = StockBasis.FREE

    @classmethod
    def default(cls, workspace_id: WorkspaceId) -> WorkspacePreferences:
        return cls(workspace_id)

    def choose_stock_basis(self, basis: StockBasis) -> bool:
        """Returns whether the choice changed, so saving the same one commits nothing."""
        if self.stock_basis is basis:
            return False
        self.stock_basis = basis
        return True
