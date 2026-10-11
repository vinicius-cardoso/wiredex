"""What a workspace has chosen about how Wiredex answers it (24-minimum-stock,
25-workspace-settings).

One row per workspace, created the first time a choice is saved: a workspace that never opened
its settings has the defaults, which `WorkspacePreferences.default` spells out. The choices are
replaced whole, as the settings page sends them.
"""

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import NewType
from uuid import UUID

# Preferences declares its own WorkspaceId, as every module does: modules don't import each
# other's domain.
WorkspaceId = NewType("WorkspaceId", UUID)

MAX_MINIMUM_STOCK = 1_000_000
MAX_RETENTION_DAYS = 3_650
DEFAULT_CODE_PREFIX = "WX"
# A letter, then up to five letters or digits: short enough that a code still fits on a drawer
# label and in inventory's 16 characters with its number.
_CODE_PREFIX = re.compile(r"^[A-Z][A-Z0-9]{0,5}$")


class PreferencesError(ValueError):
    """A choice that isn't one of the options. The message is safe to show to users."""


class StockBasis(StrEnum):
    """What a part's minimum stock is compared against. `FREE` is what is on hand and not
    reserved for a build; `TOTAL` is everything on hand, reserved or not."""

    FREE = "free"
    TOTAL = "total"

    @classmethod
    def parse(cls, text: str) -> StockBasis:
        return _parsed(cls, text, "a stock basis")


class DateFormat(StrEnum):
    """How dates are written. `LANGUAGE` follows the language the page is read in; the others
    hold whatever the language: `2026-10-11`, `11/10/2026` and `10/11/2026`."""

    LANGUAGE = "language"
    ISO = "iso"
    DAY_MONTH_YEAR = "dmy"
    MONTH_DAY_YEAR = "mdy"

    @classmethod
    def parse(cls, text: str) -> DateFormat:
        return _parsed(cls, text, "a date format")


class NumberFormat(StrEnum):
    """How numbers are written. `LANGUAGE` follows the language; `POINT` is `1,234.5` and
    `COMMA` is `1.234,5` whatever the language."""

    LANGUAGE = "language"
    POINT = "point"
    COMMA = "comma"

    @classmethod
    def parse(cls, text: str) -> NumberFormat:
        return _parsed(cls, text, "a number format")


def _parsed[E: StrEnum](enum: type[E], text: str, what: str) -> E:
    try:
        return enum(text)
    except ValueError as error:
        options = ", ".join(member.value for member in enum)
        raise PreferencesError(f"{what} is one of: {options}") from error


def code_prefix(text: str) -> str:
    """The prefix of the short codes a workspace mints, `WX` in `WX-L-0007`: trimmed and upper
    case, a letter then up to five letters or digits."""
    prefix = text.strip().upper()
    if not _CODE_PREFIX.match(prefix):
        raise PreferencesError(
            "a code prefix is a letter followed by up to five letters or digits, like WX or LAB2"
        )
    return prefix


def _within(value: int | None, low: int, high: int, what: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not low <= value <= high:
        raise PreferencesError(f"{what} is a whole number from {low:,} to {high:,}, or none")
    return value


@dataclass(frozen=True, slots=True)
class Choices:
    """Everything a workspace can choose, as one value: what a save sends and what `choose`
    compares, so saving what is already kept writes nothing."""

    # Free unless the workspace says otherwise: parts promised to a build can't be used for
    # the next one, so they shouldn't hide a part that is running out.
    stock_basis: StockBasis = StockBasis.FREE
    # The minimum of a part when neither it nor its categories set one; none watches nothing.
    default_minimum_stock: int | None = None
    # What new locations and units are coded with; codes already minted keep theirs.
    code_prefix: str = DEFAULT_CODE_PREFIX
    date_format: DateFormat = DateFormat.LANGUAGE
    number_format: NumberFormat = NumberFormat.LANGUAGE
    # How long a record stays in the trash before the nightly sweep deletes it; none keeps it
    # until it is deleted by hand, which is what the trash did before.
    trash_retention_days: int | None = None

    def __post_init__(self) -> None:
        _within(self.default_minimum_stock, 0, MAX_MINIMUM_STOCK, "a default minimum stock")
        _within(self.trash_retention_days, 1, MAX_RETENTION_DAYS, "a trash retention in days")
        object.__setattr__(self, "code_prefix", code_prefix(self.code_prefix))


@dataclass(eq=False)
class WorkspacePreferences:
    workspace_id: WorkspaceId
    stock_basis: StockBasis = StockBasis.FREE
    default_minimum_stock: int | None = None
    code_prefix: str = DEFAULT_CODE_PREFIX
    date_format: DateFormat = DateFormat.LANGUAGE
    number_format: NumberFormat = NumberFormat.LANGUAGE
    trash_retention_days: int | None = None

    @classmethod
    def default(cls, workspace_id: WorkspaceId) -> WorkspacePreferences:
        return cls(workspace_id)

    @property
    def choices(self) -> Choices:
        return Choices(
            self.stock_basis,
            self.default_minimum_stock,
            self.code_prefix,
            self.date_format,
            self.number_format,
            self.trash_retention_days,
        )

    def choose(self, choices: Choices) -> bool:
        """Replaces every choice; returns whether anything changed, so saving the same ones
        commits nothing."""
        if self.choices == choices:
            return False
        self.stock_basis = choices.stock_basis
        self.default_minimum_stock = choices.default_minimum_stock
        self.code_prefix = choices.code_prefix
        self.date_format = choices.date_format
        self.number_format = choices.number_format
        self.trash_retention_days = choices.trash_retention_days
        return True

    def choose_stock_basis(self, basis: StockBasis) -> bool:
        """Only the basis changed, the rest kept: what a caller that knows one choice saves."""
        return self.choose(replace(self.choices, stock_basis=basis))
