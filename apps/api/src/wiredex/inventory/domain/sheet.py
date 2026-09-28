"""A sheet: CSV text with a header row and one entry in each later row, read and written.

The sheet knows how a sheet is written, nothing about what it means: which part a row names,
whether its quantity reads, where its location is. That is the plan's job, so every cell is
kept exactly as read, and trimming stays with the value objects that read the cells.

Two rules are restated from catalog, because inventory can't import it (ADR 0001): how a name
is folded before it is compared (`folding`, which location paths share), and which text can
be an attribute key.
"""

import csv
import io
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from wiredex.inventory.domain.errors import SheetUnreadableError
from wiredex.inventory.domain.folding import fold

# Sized for one transaction on the small host (design decision 10). The request schema caps
# the characters before a sheet is read; the reader caps the entries and the columns.
MAX_SHEET_CHARACTERS = 262_144
MAX_SHEET_ENTRIES = 500
MAX_SHEET_COLUMNS = 64

# Tab first, then `;`, then `,`, the order the pinout paste tries them: a spreadsheet's copy
# is tab-separated and its cells may hold either, and a spreadsheet set to Brazilian
# Portuguese saves CSV with semicolons, because its comma is the decimal point.
SEPARATORS = ("\t", ";", ",")

# The csv module refuses a cell longer than 131,072 characters, and a quote left open runs
# the rest of the text into one cell. No cell outgrows the sheet, so allowing that much keeps
# an unclosed quote a row the preview can show rather than a crash.
csv.field_size_limit(max(csv.field_size_limit(), MAX_SHEET_CHARACTERS))


class Column(StrEnum):
    """The nine fixed columns, named as the template spells them. Any other header is an
    attribute key."""

    CATEGORY = "category"
    NAME = "name"
    MANUFACTURER = "manufacturer"
    MPN = "mpn"
    PACKAGE = "package"
    LOCATION = "location"
    QUANTITY = "quantity"
    SERIAL = "serial"
    MAC = "mac"


class SheetRefusal(StrEnum):
    """Why a sheet can't be read at all, as `SheetUnreadableError` carries it. The web
    translates each one; a row's problems are the plan's, not these."""

    NOT_UTF8 = "not_utf8"
    EMPTY = "empty"
    UNKNOWN_COLUMN = "unknown_column"
    DUPLICATE_COLUMN = "duplicate_column"
    TOO_MANY_COLUMNS = "too_many_columns"
    TOO_MANY_ROWS = "too_many_rows"


@dataclass(frozen=True, slots=True)
class SheetRow:
    """One entry of a sheet: its number and every column's cell, as read."""

    number: int  # as the spreadsheet numbers it; the header is row 1
    cells: Mapping[str, str]  # a fixed column's value or an attribute key → the cell as read
    overflows: bool  # a non-blank cell beyond the header's columns


@dataclass(frozen=True, slots=True)
class Sheet:
    columns: tuple[str, ...]
    rows: tuple[SheetRow, ...]


def read_sheet(text: str) -> Sheet:
    """The sheet `text` holds, or `SheetUnreadableError` saying why it can't be read.

    The first non-blank record is the header, and its line picks the separator. Every record
    counts toward the row numbers, blank or not, so the preview's row 7 is the spreadsheet's
    row 7 (requirement 4.1). A row missing trailing cells reads them as blank; one holding a
    non-blank cell past the header's columns is kept and marked, since that cell may be an
    unquoted separator (requirement 4.7).
    """
    readable = text.removeprefix(_BYTE_ORDER_MARK)
    if any(mark in readable for mark in _UNDECODED):
        raise SheetUnreadableError(
            SheetRefusal.NOT_UTF8,
            "the sheet isn't UTF-8 text: save it as CSV UTF-8 and choose it again",
        )
    reader = csv.reader(io.StringIO(readable, newline=""), delimiter=_separator_of(readable))
    records = enumerate(reader, start=1)
    header = _Header.read(_header_record(records))
    return Sheet(header.columns, _entries(records, header))


def write_sheet(sheet: Sheet, separator: str = ",") -> str:
    """The sheet as text `read_sheet` reads back as the same sheet (property 1).

    Cells are quoted only where they need it (a separator, a quote or a line break), with
    CRLF between records as RFC 4180 has it. A fixed column is written in English and an
    attribute as its key.
    """
    text = io.StringIO()
    writer = csv.writer(text, delimiter=separator, lineterminator="\r\n")
    writer.writerow(sheet.columns)
    writer.writerows([row.cells.get(column, "") for column in sheet.columns] for row in sheet.rows)
    return text.getvalue()


def template_sheet() -> Sheet:
    """The import template: the nine fixed columns and no entries (requirement 4.9)."""
    return Sheet(tuple(Column), ())


type _Records = Iterator[tuple[int, list[str]]]


@dataclass(frozen=True, slots=True)
class _Header:
    """Which column each position of a record holds. A blank header cell holds none, so a
    cell under it is overflow, as a cell past the last column is."""

    positions: tuple[tuple[int, str], ...]

    @classmethod
    def read(cls, record: Sequence[str]) -> _Header:
        named = [(index, cell) for index, cell in enumerate(record) if cell.strip()]
        if len(named) > MAX_SHEET_COLUMNS:
            raise SheetUnreadableError(
                SheetRefusal.TOO_MANY_COLUMNS,
                f"a sheet holds at most {MAX_SHEET_COLUMNS} columns, and this one has {len(named)}",
            )
        positions = tuple((index, _column_named(cell)) for index, cell in named)
        _refuse_repeats(record, positions)
        return cls(positions)

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(column for _, column in self.positions)

    def row(self, number: int, record: Sequence[str]) -> SheetRow:
        cells = {
            column: record[index] if index < len(record) else "" for index, column in self.positions
        }
        held = {index for index, _ in self.positions}
        overflows = any(cell.strip() for index, cell in enumerate(record) if index not in held)
        return SheetRow(number, cells, overflows)


def _header_record(records: _Records) -> list[str]:
    for _, record in records:
        if not _is_blank(record):
            return record
    raise SheetUnreadableError(SheetRefusal.EMPTY, "the sheet has no header row naming its columns")


def _entries(records: _Records, header: _Header) -> tuple[SheetRow, ...]:
    rows: list[SheetRow] = []
    for number, record in records:
        if _is_blank(record):
            continue
        if len(rows) == MAX_SHEET_ENTRIES:
            raise SheetUnreadableError(
                SheetRefusal.TOO_MANY_ROWS,
                f"a sheet holds at most {MAX_SHEET_ENTRIES} entries: split it into two",
            )
        rows.append(header.row(number, record))
    return tuple(rows)


def _column_named(header: str) -> str:
    """The fixed column a header spells, in either language, or else the attribute key it
    is; `unknown_column` when it is neither. A fixed column wins over an attribute of the
    same key."""
    fixed = _FIXED.get(fold(header))
    if fixed is not None:
        return fixed
    key = header.strip().lower()
    if _ATTRIBUTE_KEY.fullmatch(key):
        return key
    raise SheetUnreadableError(
        SheetRefusal.UNKNOWN_COLUMN,
        f"{_shown(header)!r} is neither a column like name or quantity nor an attribute key "
        f"like resistance",
        _shown(header),
    )


def _refuse_repeats(record: Sequence[str], positions: Sequence[tuple[int, str]]) -> None:
    first: dict[str, int] = {}
    for index, column in positions:
        if column in first:
            raise SheetUnreadableError(
                SheetRefusal.DUPLICATE_COLUMN,
                f"{_shown(record[first[column]])!r} and {_shown(record[index])!r} are both "
                f"the {column} column",
                column,
            )
        first[column] = index


def _separator_of(text: str) -> str:
    """The separator the header's line holds: tab, else `;`, else `,` (requirement 4.2).

    Read off the raw text, since the csv reader needs it before it reads anything: the first
    line holding more than spacing. That is the header's line, unless blank rows written as
    bare separators come first, and a spreadsheet writes those with the header's separator.
    """
    lines = io.StringIO(text, newline="")
    header = next((line for line in lines if line.strip()), "")
    return next((separator for separator in SEPARATORS if separator in header), ",")


def _is_blank(record: Sequence[str]) -> bool:
    return not any(cell.strip() for cell in record)


def _shown(header: str) -> str:
    """A header in a refusal: trimmed, its spacing collapsed, otherwise as typed."""
    return " ".join(header.split())


_BYTE_ORDER_MARK = "\ufeff"

# U+FFFD is what a browser leaves for every byte that wasn't UTF-8. NUL is how a UTF-16 file
# (a spreadsheet's "Unicode text") reads when taken for UTF-8, and no text column stores it.
_UNDECODED = ("\ufffd", "\x00")

# Catalog's AttributeKey rule, restated: after trimming and lower-casing, a letter, then
# letters, digits or `_`, at most 40 in all. A header catalog would refuse as a key is
# refused here, naming it, rather than reaching the plan as a column no category defines.
_MAX_ATTRIBUTE_KEY_LENGTH = 40
_ATTRIBUTE_KEY = re.compile(rf"[a-z][a-z0-9_]{{0,{_MAX_ATTRIBUTE_KEY_LENGTH - 1}}}")

# Every header a fixed column answers to, in English and Brazilian Portuguese, compared
# folded: `Código do fabricante`, `CODIGO DO  FABRICANTE` and `codigo do fabricante` are one.
_SPELLINGS: Mapping[Column, tuple[str, ...]] = {
    Column.CATEGORY: ("category", "categoria"),
    Column.NAME: ("name", "nome"),
    Column.MANUFACTURER: ("manufacturer", "fabricante"),
    Column.MPN: ("mpn", "part number", "código do fabricante"),
    Column.PACKAGE: ("package", "encapsulamento"),
    Column.LOCATION: ("location", "local", "localização"),
    Column.QUANTITY: ("quantity", "qty", "quantidade", "qtd"),
    Column.SERIAL: ("serial", "serial number", "número de série"),
    Column.MAC: ("mac", "mac address", "endereço mac"),
}
_FIXED: Mapping[str, Column] = {
    fold(spelling): column for column, spellings in _SPELLINGS.items() for spelling in spellings
}
