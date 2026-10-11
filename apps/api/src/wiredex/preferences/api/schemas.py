from typing import Literal, Self

from pydantic import BaseModel, Field

from wiredex.preferences.domain.preferences import (
    MAX_MINIMUM_STOCK,
    MAX_RETENTION_DAYS,
    Choices,
    DateFormat,
    NumberFormat,
    StockBasis,
    WorkspacePreferences,
)

# Spelled out here so the generated client types them; a test keeps each in step with its enum.
type StockBasisName = Literal["free", "total"]
type DateFormatName = Literal["language", "iso", "dmy", "mdy"]
type NumberFormatName = Literal["language", "point", "comma"]


class PreferencesResponse(BaseModel):
    """A workspace's settings.

    `stock_basis` is what a minimum stock is compared against: `free`, on hand and not
    reserved, or `total`. `default_minimum_stock` is the minimum of a part when neither it nor
    its categories set one. `code_prefix` starts the short codes of new locations and units.
    `date_format` and `number_format` say how the pages write them, `language` following the
    reader's. `trash_retention_days` is how long a record stays in the trash before the nightly
    sweep deletes it; null keeps it until it is deleted by hand.
    """

    stock_basis: StockBasisName
    default_minimum_stock: int | None
    code_prefix: str
    date_format: DateFormatName
    number_format: NumberFormatName
    trash_retention_days: int | None

    @classmethod
    def from_preferences(cls, preferences: WorkspacePreferences) -> Self:
        return cls.model_validate(
            {
                "stock_basis": preferences.stock_basis.value,
                "default_minimum_stock": preferences.default_minimum_stock,
                "code_prefix": preferences.code_prefix,
                "date_format": preferences.date_format.value,
                "number_format": preferences.number_format.value,
                "trash_retention_days": preferences.trash_retention_days,
            }
        )


class PreferencesRequest(BaseModel):
    """The settings, replacing the saved ones whole. The ones left out take their defaults."""

    stock_basis: StockBasisName = "free"
    default_minimum_stock: int | None = Field(default=None, ge=0, le=MAX_MINIMUM_STOCK)
    # Its shape is the domain's to check, so the refusal says what a prefix looks like.
    code_prefix: str = Field(default="WX", max_length=32)
    date_format: DateFormatName = "language"
    number_format: NumberFormatName = "language"
    trash_retention_days: int | None = Field(default=None, ge=1, le=MAX_RETENTION_DAYS)

    def choices(self) -> Choices:
        return Choices(
            stock_basis=StockBasis(self.stock_basis),
            default_minimum_stock=self.default_minimum_stock,
            code_prefix=self.code_prefix,
            date_format=DateFormat(self.date_format),
            number_format=NumberFormat(self.number_format),
            trash_retention_days=self.trash_retention_days,
        )
