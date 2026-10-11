from typing import Literal, Self

from pydantic import BaseModel

from wiredex.preferences.domain.preferences import StockBasis, WorkspacePreferences

# Spelled out here so the generated client types it; a test keeps it in step with the enum.
type StockBasisName = Literal["free", "total"]


class PreferencesResponse(BaseModel):
    """A workspace's settings. `stock_basis` is what a minimum stock is compared against:
    `free`, on hand and not reserved, or `total`, everything on hand."""

    stock_basis: StockBasisName

    @classmethod
    def from_preferences(cls, preferences: WorkspacePreferences) -> Self:
        basis: StockBasisName = "total" if preferences.stock_basis is StockBasis.TOTAL else "free"
        return cls(stock_basis=basis)


class PreferencesRequest(BaseModel):
    """The settings, replacing the saved ones whole."""

    stock_basis: StockBasisName
