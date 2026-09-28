"""Reading and writing a sheet: CSV text with a header row and one entry in each later row.

The reader picks the separator off the header's line, leaves quoting to the csv module, reads
each header as a fixed column in either language or as an attribute key, and numbers rows as
the spreadsheet does. Everything it can't read is one `SheetUnreadableError` with its code.
Property 1, the round trip through `write_sheet`, is the last test.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.inventory.domain.errors import SheetUnreadableError
from wiredex.inventory.domain.sheet import (
    MAX_SHEET_COLUMNS,
    MAX_SHEET_ENTRIES,
    SEPARATORS,
    Column,
    Sheet,
    SheetRefusal,
    SheetRow,
    read_sheet,
    template_sheet,
    write_sheet,
)


def refusal(text: str) -> SheetUnreadableError:
    with pytest.raises(SheetUnreadableError) as refused:
        read_sheet(text)
    return refused.value


def cells_of(sheet: Sheet) -> list[dict[str, str]]:
    return [dict(row.cells) for row in sheet.rows]


# --- Separators and quoting ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "cells"),
    [
        # A tab wins, so the commas and semicolons in its cells are text.
        ("name\tpackage\n4k7; 1%\t0805, reel\n", {"name": "4k7; 1%", "package": "0805, reel"}),
        # Then a semicolon, as a spreadsheet in Portuguese saves it, its comma a decimal point.
        ("name;package\n4,7 µF;0805\n", {"name": "4,7 µF", "package": "0805"}),
        # Else a comma.
        ("name,package\n4k7,0805\n", {"name": "4k7", "package": "0805"}),
    ],
    ids=["tab", "semicolon", "comma"],
)
def test_the_header_line_picks_the_separator(text: str, cells: dict[str, str]) -> None:
    assert cells_of(read_sheet(text)) == [cells]


def test_a_semicolon_in_a_comma_sheets_cells_is_text() -> None:
    # Only the header's line picks: a later line holding a semicolon doesn't change the rule.
    sheet = read_sheet("name,package\n10k; thin film,0805\n")

    assert cells_of(sheet) == [{"name": "10k; thin film", "package": "0805"}]


def test_quoted_cells_keep_separators_doubled_quotes_and_line_breaks() -> None:
    text = 'name,package\n"10k, 1%","say ""hi"""\n"two\r\nlines","one\nmore"\n'

    assert cells_of(read_sheet(text)) == [
        {"name": "10k, 1%", "package": 'say "hi"'},
        {"name": "two\r\nlines", "package": "one\nmore"},
    ]


def test_cells_are_kept_exactly_as_read() -> None:
    # Trimming is the value objects' job, in the plan.
    sheet = read_sheet("name,mpn\n  10k  , RC0805 \n")

    assert cells_of(sheet) == [{"name": "  10k  ", "mpn": " RC0805 "}]


def test_crlf_and_a_bare_cr_end_records_as_a_newline_does() -> None:
    sheet = read_sheet("name\r\nA\rB\nC")

    assert cells_of(sheet) == [{"name": "A"}, {"name": "B"}, {"name": "C"}]


def test_a_cell_longer_than_the_csv_default_limit_still_reads() -> None:
    # A quote left open runs the rest of the text into one cell; the sheet still reads.
    cell = "x" * 200_000

    assert cells_of(read_sheet(f'name\n"{cell}')) == [{"name": cell}]


# --- Encoding --------------------------------------------------------------------------------


def test_a_leading_byte_order_mark_is_dropped() -> None:
    # Kept, it would glue itself to the first header and make it unknown.
    assert read_sheet("\ufeffname,mpn\nA,B\n").columns == ("name", "mpn")


@pytest.mark.parametrize(
    "text",
    [
        "name,mpn\nResist\ufffdr,B\n",  # what a browser leaves for a byte that wasn't UTF-8
        "n\x00a\x00m\x00e\x00\n\x00",  # a UTF-16 file taken for UTF-8
    ],
    ids=["replacement character", "nul"],
)
def test_text_that_was_not_utf8_is_refused(text: str) -> None:
    refused = refusal(text)

    assert refused.code is SheetRefusal.NOT_UTF8
    assert refused.column is None
    assert "UTF-8" in str(refused)


# --- Headers -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "column"),
    [
        ("category", Column.CATEGORY),
        ("CATEGORY", Column.CATEGORY),
        ("Categoria", Column.CATEGORY),
        ("name", Column.NAME),
        ("  Nome  ", Column.NAME),
        ("Manufacturer", Column.MANUFACTURER),
        ("FABRICANTE", Column.MANUFACTURER),
        ("MPN", Column.MPN),
        ("Part  Number", Column.MPN),
        ("part\u00a0number", Column.MPN),  # a no-break space is spacing too
        ("Código do Fabricante", Column.MPN),
        ("codigo do  fabricante", Column.MPN),
        ("\uff2d\uff30\uff2e", Column.MPN),  # full-width letters read as their plain ones
        ("Package", Column.PACKAGE),
        ("Encapsulamento", Column.PACKAGE),
        ("location", Column.LOCATION),
        ("LOCAL", Column.LOCATION),
        ("Localização", Column.LOCATION),
        ("localizacao", Column.LOCATION),
        ("Quantity", Column.QUANTITY),
        ("qty", Column.QUANTITY),
        ("Quantidade", Column.QUANTITY),
        ("QTD", Column.QUANTITY),
        ("Serial", Column.SERIAL),
        ("serial NUMBER", Column.SERIAL),
        ("Número de Série", Column.SERIAL),
        ("numero de serie", Column.SERIAL),
        ("MAC", Column.MAC),
        ("Mac Address", Column.MAC),
        ("Endereço MAC", Column.MAC),
        ("endereco mac", Column.MAC),
    ],
)
def test_every_fixed_column_reads_in_either_language(header: str, column: Column) -> None:
    sheet = read_sheet(f"{header},resistance\nx,10k\n")

    assert sheet.columns == (column, "resistance")
    assert sheet.rows[0].cells[column] == "x"


def test_every_fixed_column_answers_to_its_english_name() -> None:
    assert read_sheet(",".join(Column)).columns == tuple(Column)


@pytest.mark.parametrize(
    ("header", "key"),
    [("resistance", "resistance"), ("Resistance", "resistance"), (" i2c_address ", "i2c_address")],
)
def test_any_other_header_is_an_attribute_key(header: str, key: str) -> None:
    sheet = read_sheet(f"name,{header}\n10k,10000\n")

    assert sheet.columns == ("name", key)
    assert sheet.rows[0].cells == {"name": "10k", key: "10000"}


@pytest.mark.parametrize(
    "header",
    [
        "Resistência",  # an accent: catalog's keys are ASCII
        "2nd source",  # a key starts with a letter
        "part-number",  # letters, digits and _ only
        "tolerance pct",  # no spacing inside a key
        "k" * 41,  # at most 40
    ],
)
def test_a_header_that_is_neither_is_an_unknown_column(header: str) -> None:
    refused = refusal(f"name,{header}\n10k,x\n")

    assert refused.code is SheetRefusal.UNKNOWN_COLUMN
    assert refused.column == header
    assert header in str(refused)


def test_an_attribute_key_at_its_cap_reads() -> None:
    assert read_sheet(f"name,{'k' * 40}\n").columns == ("name", "k" * 40)


@pytest.mark.parametrize(
    ("header", "column"),
    [
        ("name,Nome", "name"),
        ("quantity;quantidade", "quantity"),  # two languages, one column
        ("qty,mpn,QTY", "quantity"),
        ("resistance,Resistance", "resistance"),  # an attribute key, in two cases
    ],
)
def test_a_column_given_twice_is_refused(header: str, column: str) -> None:
    refused = refusal(f"{header}\n")

    assert refused.code is SheetRefusal.DUPLICATE_COLUMN
    assert refused.column == column
    assert f"the {column} column" in str(refused)


def test_a_blank_header_cell_is_skipped_and_its_cells_overflow() -> None:
    sheet = read_sheet("name,,mpn\n10k,stray,RC0805\n4k7,,RC0805B\n")

    assert sheet.columns == ("name", "mpn")
    assert sheet.rows == (
        SheetRow(2, {"name": "10k", "mpn": "RC0805"}, overflows=True),
        SheetRow(3, {"name": "4k7", "mpn": "RC0805B"}, overflows=False),
    )


@pytest.mark.parametrize("text", ["", "\ufeff", "\n  \n\t\n", ",,\n,\n", ";;\n\n;;\n", '"",""\n'])
def test_a_sheet_without_a_header_is_empty(text: str) -> None:
    assert refusal(text).code is SheetRefusal.EMPTY


# --- Rows ------------------------------------------------------------------------------------


def test_blank_rows_are_skipped_but_keep_the_spreadsheets_numbers() -> None:
    # Blank lines above the header count too: the spreadsheet shows the header as row 3.
    text = '\n,\nname,mpn\n10k,A\n\n  ,\t\n4k7,B\n"multi\nline",C\nlast,D\n'

    sheet = read_sheet(text)

    assert [row.number for row in sheet.rows] == [4, 7, 8, 9]
    assert [row.cells["name"] for row in sheet.rows] == ["10k", "4k7", "multi\nline", "last"]


def test_a_short_row_reads_its_missing_cells_as_blank() -> None:
    sheet = read_sheet("name,mpn,package\n10k\n")

    assert sheet.rows == (SheetRow(2, {"name": "10k", "mpn": "", "package": ""}, False),)


def test_a_non_blank_cell_past_the_header_overflows() -> None:
    # 10k, 1% unquoted in a comma sheet: the cell split in two, and the row says so.
    sheet = read_sheet("name,package\n10k, 1%,0805\n4k7,0805,  \n")

    assert sheet.rows == (
        SheetRow(2, {"name": "10k", "package": " 1%"}, overflows=True),
        SheetRow(3, {"name": "4k7", "package": "0805"}, overflows=False),  # a blank cell past
    )


def test_a_row_holding_only_an_overflowing_cell_is_still_an_entry() -> None:
    assert read_sheet("name,mpn\n,,stray\n").rows == (SheetRow(2, {"name": "", "mpn": ""}, True),)


# --- Caps ------------------------------------------------------------------------------------


def test_a_sheet_holds_its_cap_of_entries_whatever_its_blank_rows() -> None:
    text = "name\n" + "10k\n\n" * MAX_SHEET_ENTRIES

    sheet = read_sheet(text)

    assert len(sheet.rows) == MAX_SHEET_ENTRIES
    assert sheet.rows[-1].number == 2 * MAX_SHEET_ENTRIES


def test_one_entry_past_the_cap_is_refused() -> None:
    refused = refusal("name\n" + "10k\n" * (MAX_SHEET_ENTRIES + 1))

    assert refused.code is SheetRefusal.TOO_MANY_ROWS
    assert refused.column is None


def test_a_sheet_holds_its_cap_of_columns() -> None:
    keys = [f"k{index}" for index in range(MAX_SHEET_COLUMNS)]

    assert read_sheet(",".join(keys)).columns == tuple(keys)


def test_one_column_past_the_cap_is_refused() -> None:
    # Counted before any header is read: the 65th would be unknown, but the count comes first.
    headers = [f"k{index}" for index in range(MAX_SHEET_COLUMNS)] + ["not a key"]

    refused = refusal(",".join(headers))

    assert refused.code is SheetRefusal.TOO_MANY_COLUMNS
    assert refused.column is None
    assert "65" in str(refused)


def test_blank_header_cells_dont_count_toward_the_cap() -> None:
    keys = [f"k{index}" for index in range(MAX_SHEET_COLUMNS)]

    assert read_sheet(",".join(keys) + ",,,\n").columns == tuple(keys)


# --- Writing -----------------------------------------------------------------------------------


def test_writing_quotes_only_the_cells_that_need_it() -> None:
    sheet = Sheet(
        ("name", "mpn"),
        (
            SheetRow(2, {"name": "10k;1%", "mpn": 'say "hi"'}, False),
            SheetRow(3, {"name": "4k7"}, False),
        ),
    )

    assert write_sheet(sheet, ";") == 'name;mpn\r\n"10k;1%";"say ""hi"""\r\n4k7;\r\n'


def test_the_template_is_the_nine_fixed_columns_in_english() -> None:
    text = write_sheet(template_sheet())

    assert text == "category,name,manufacturer,mpn,package,location,quantity,serial,mac\r\n"
    assert read_sheet(text) == Sheet(tuple(Column), ())


def test_there_are_exactly_nine_fixed_columns() -> None:
    assert [column.value for column in Column] == [
        "category",
        "name",
        "manufacturer",
        "mpn",
        "package",
        "location",
        "quantity",
        "serial",
        "mac",
    ]


# --- Property 1: a sheet survives its own text ----------------------------------------------
#
# Headers are fixed columns and attribute keys. A key that is also a fixed column's spelling
# (`qty`, `local`, `nome`) reads as that column, which is the rule, not a round trip, so the
# keys drawn skip them. Cells lean on what quoting has to carry: separators, quotes, both line
# endings, and any character but the two a sheet can't hold.

# Every one-word spelling of a fixed column, folded: the ones a drawn key could collide with.
_FIXED_SPELLINGS = frozenset(
    [
        *(column.value for column in Column),
        *["categoria", "nome", "fabricante", "encapsulamento", "local", "localizacao"],
        *["qty", "quantidade", "qtd"],
    ]
)
_KEYS = st.from_regex(r"[a-z][a-z0-9_]{0,39}", fullmatch=True).filter(
    lambda key: key not in _FIXED_SPELLINGS
)
_HEADERS: st.SearchStrategy[str] = st.sampled_from(Column) | _KEYS
_PIECES = st.sampled_from(["\t", ";", ",", '"', '""', "\r", "\n", "\r\n", " ", "\u2028"])
_CELLS = st.lists(_PIECES | st.characters(exclude_characters="\x00\ufffd"), max_size=10).map(
    "".join
)


@st.composite
def sheets(draw: st.DrawFn) -> Sheet:
    columns = draw(st.lists(_HEADERS, min_size=2, max_size=8, unique=True))
    row = st.fixed_dictionaries(dict.fromkeys(columns, _CELLS)).filter(
        lambda cells: any(cell.strip() for cell in cells.values())
    )
    rows = draw(st.lists(row, max_size=6))
    return Sheet(
        tuple(columns),
        tuple(SheetRow(number, cells, False) for number, cells in enumerate(rows, start=2)),
    )


@pytest.mark.parametrize("separator", SEPARATORS, ids=["tab", "semicolon", "comma"])
@given(sheet=sheets())
def test_a_sheet_survives_its_own_text(separator: str, sheet: Sheet) -> None:
    """Property 1: a sheet survives its own text.

    For any header of at least two distinct columns and any rows with a non-blank cell,
    reading what `write_sheet` wrote with each separator gives back the same columns and the
    same cells, row for row, numbered from 2 as the spreadsheet numbers them.

    **Validates: Requirements 4.2, 4.8**
    """
    assert read_sheet(write_sheet(sheet, separator)) == sheet
