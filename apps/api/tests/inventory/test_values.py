import pytest

from wiredex.inventory.domain.errors import (
    InvalidLocationNameError,
    InvalidNoteError,
    InvalidQuantityError,
    InvalidShortCodeError,
    InventoryError,
)
from wiredex.inventory.domain.values import (
    MAX_LOCATION_NAME_LENGTH,
    MAX_NOTE_LENGTH,
    LocationName,
    MovementKind,
    MovementReason,
    Note,
    Quantity,
    ShortCode,
)


class TestLocationName:
    def test_is_trimmed_and_has_its_whitespace_collapsed(self) -> None:
        assert LocationName("  Drawer   3  ").value == "Drawer 3"

    def test_keeps_the_case_it_was_typed_in(self) -> None:
        # Case is the owner's choice; a location name is not lower-cased.
        assert LocationName("Lab Bench").value == "Lab Bench"

    def test_accepts_its_cap_and_refuses_one_character_more(self) -> None:
        assert LocationName("x" * MAX_LOCATION_NAME_LENGTH).value == "x" * MAX_LOCATION_NAME_LENGTH
        with pytest.raises(InvalidLocationNameError, match="between 1 and 80 characters"):
            LocationName("x" * (MAX_LOCATION_NAME_LENGTH + 1))

    @pytest.mark.parametrize("text", ["", "   ", "\t\n"])
    def test_blank_is_never_a_name(self, text: str) -> None:
        with pytest.raises(InvalidLocationNameError):
            LocationName(text)


class TestShortCode:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("WX-L-0001", "WX-L-0001"),
            ("wx-l-0001", "WX-L-0001"),  # upper-cased
            ("  WX-U-0042  ", "WX-U-0042"),  # trimmed
            ("WX-L-10000", "WX-L-10000"),  # five digits past 9999
        ],
    )
    def test_is_trimmed_and_upper_cased(self, text: str, expected: str) -> None:
        assert ShortCode(text).value == expected

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "WX-L-1",  # fewer than four digits
            "WX-L-001",
            "WX-X-0001",  # only L or U
            "WX-0001",  # no kind
            "L-0001",  # no prefix
            "WX-L-0001x",  # trailing junk
            "WX-L-",
        ],
    )
    def test_rejects_anything_that_is_not_the_scheme(self, text: str) -> None:
        with pytest.raises(InvalidShortCodeError, match="short code like WX-L-0007"):
            ShortCode(text)

    @pytest.mark.parametrize(
        ("number", "expected"),
        [(1, "WX-L-0001"), (7, "WX-L-0007"), (9999, "WX-L-9999")],
    )
    def test_for_location_formats_four_digits(self, number: int, expected: str) -> None:
        assert ShortCode.for_location(number).value == expected

    @pytest.mark.parametrize(
        ("number", "expected"),
        [(1, "WX-U-0001"), (42, "WX-U-0042")],
    )
    def test_for_unit_formats_four_digits(self, number: int, expected: str) -> None:
        assert ShortCode.for_unit(number).value == expected

    @pytest.mark.parametrize(
        ("number", "expected"),
        [(10000, "WX-L-10000"), (123456, "WX-L-123456")],
    )
    def test_rolls_over_to_five_digits_past_9999(self, number: int, expected: str) -> None:
        # The width is display, not identity: a workspace past 9999 widens rather than wraps.
        assert ShortCode.for_location(number).value == expected


class TestQuantity:
    @pytest.mark.parametrize("value", [0, 1, 180, 10_000])
    def test_accepts_non_negative_counts(self, value: int) -> None:
        assert int(Quantity(value)) == value

    def test_refuses_a_negative_count(self) -> None:
        with pytest.raises(InvalidQuantityError, match="can't be negative"):
            Quantity(-1)

    def test_zero_is_allowed_because_an_empty_lot_is_normal(self) -> None:
        assert int(Quantity(0)) == 0

    @pytest.mark.parametrize("value", [True, False])
    def test_a_bool_is_not_a_quantity(self, value: bool) -> None:
        # bool subclasses int; a count is not a flag.
        with pytest.raises(InvalidQuantityError):
            Quantity(value)


class TestMovementKind:
    def test_is_exactly_adr_0002s_seven_names(self) -> None:
        assert [kind.value for kind in MovementKind] == [
            "RECEIVE",
            "ADJUST",
            "MOVE",
            "RESERVE",
            "RELEASE",
            "CONSUME",
            "RETURN",
        ]

    def test_is_a_str_enum_so_it_reaches_json_as_its_name(self) -> None:
        assert MovementKind("RECEIVE") is MovementKind.RECEIVE
        assert str(MovementKind.MOVE) == "MOVE"


class TestMovementReason:
    def test_is_exactly_the_five_adjust_reasons(self) -> None:
        assert [reason.value for reason in MovementReason] == [
            "recount",
            "damaged",
            "lost",
            "found",
            "correction",
        ]

    @pytest.mark.parametrize("word", ["recount", "damaged", "lost", "found", "correction"])
    def test_accepts_each_reason_word(self, word: str) -> None:
        assert MovementReason(word).value == word

    def test_refuses_a_word_outside_the_vocabulary(self) -> None:
        with pytest.raises(ValueError, match="broken"):
            MovementReason("broken")


class TestNote:
    def test_is_trimmed_and_has_its_whitespace_collapsed(self) -> None:
        assert Note("  a   long  day  ").value == "a long day"

    def test_accepts_its_cap_and_refuses_one_character_more(self) -> None:
        assert Note("x" * MAX_NOTE_LENGTH).value == "x" * MAX_NOTE_LENGTH
        with pytest.raises(InvalidNoteError, match="between 1 and 500 characters"):
            Note("x" * (MAX_NOTE_LENGTH + 1))

    @pytest.mark.parametrize("text", ["", "   ", "\t\n"])
    def test_blank_is_never_a_note(self, text: str) -> None:
        with pytest.raises(InvalidNoteError):
            Note(text)


def test_every_value_error_is_an_inventory_error() -> None:
    # The API maps InventoryError to 422 for any bad value.
    for error in (
        InvalidLocationNameError,
        InvalidShortCodeError,
        InvalidQuantityError,
        InvalidNoteError,
    ):
        assert issubclass(error, InventoryError)
