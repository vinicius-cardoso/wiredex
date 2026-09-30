import pytest

from wiredex.firmware.domain.errors import (
    InvalidChangelogError,
    InvalidDescriptionError,
    InvalidNameError,
    InvalidTargetError,
)
from wiredex.firmware.domain.values import (
    MAX_NAME_LENGTH,
    MAX_TARGET_LENGTH,
    MAX_TEXT_LENGTH,
    BoardTarget,
    Changelog,
    Description,
    FirmwareName,
    Framework,
)

# Controls that aren't whitespace, so collapsing leaves them in place: NUL, a bell, DEL, and a
# C1 control (CSI) that a paste from a terminal can carry.
_CONTROLS = ["weather\x00station", "bell\x07", "del\x7f", "\x9b31m red"]


class TestFirmwareName:
    def test_is_trimmed_and_has_its_whitespace_collapsed(self) -> None:
        assert FirmwareName("  Weather \t  station \n").value == "Weather station"

    def test_keeps_the_case_it_was_typed_in(self) -> None:
        assert FirmwareName("Greenhouse Controller").value == "Greenhouse Controller"

    def test_accepts_its_cap_and_refuses_one_character_more(self) -> None:
        name = "x" * MAX_NAME_LENGTH
        assert FirmwareName(name).value == name
        with pytest.raises(InvalidNameError, match="between 1 and 120 characters"):
            FirmwareName(name + "x")

    def test_the_cap_counts_after_the_whitespace_is_collapsed(self) -> None:
        name = f"  {'x' * (MAX_NAME_LENGTH - 2)} \t\n y  "
        assert FirmwareName(name).value == f"{'x' * (MAX_NAME_LENGTH - 2)} y"

    @pytest.mark.parametrize("text", ["", "   ", "\t\n"])
    def test_blank_is_never_a_name(self, text: str) -> None:
        with pytest.raises(InvalidNameError):
            FirmwareName(text)

    @pytest.mark.parametrize("text", _CONTROLS)
    def test_a_control_character_is_refused(self, text: str) -> None:
        with pytest.raises(InvalidNameError, match="control character"):
            FirmwareName(text)

    def test_tabs_and_line_breaks_are_whitespace_not_controls(self) -> None:
        assert FirmwareName("Weather\tstation\r\nrewrite").value == "Weather station rewrite"

    def test_two_cases_of_one_name_fold_alike(self) -> None:
        assert FirmwareName("Weather Station").fold() == FirmwareName("weather station").fold()
        assert str(FirmwareName("Weather Station")) == "Weather Station"


class TestBoardTarget:
    @pytest.mark.parametrize(
        "text",
        ["esp32:esp32:esp32", "RPI_PICO", "arduino:avr:uno", "esp32:esp32:esp32s3:USBMode=hwcdc"],
    )
    def test_keeps_a_toolchains_spelling_as_it_is(self, text: str) -> None:
        assert BoardTarget(text).value == text
        assert str(BoardTarget(text)) == text

    def test_is_trimmed_and_has_its_whitespace_collapsed(self) -> None:
        assert BoardTarget("  Raspberry  Pi\tPico \n").value == "Raspberry Pi Pico"

    def test_accepts_its_cap_and_refuses_one_character_more(self) -> None:
        target = "x" * MAX_TARGET_LENGTH
        assert BoardTarget(target).value == target
        with pytest.raises(InvalidTargetError, match="between 1 and 200 characters"):
            BoardTarget(target + "x")

    @pytest.mark.parametrize("text", ["", "  ", "\n"])
    def test_blank_is_refused(self, text: str) -> None:
        with pytest.raises(InvalidTargetError):
            BoardTarget(text)

    @pytest.mark.parametrize("text", _CONTROLS)
    def test_a_control_character_is_refused(self, text: str) -> None:
        with pytest.raises(InvalidTargetError, match="control character"):
            BoardTarget(text)


class TestFramework:
    def test_is_exactly_the_five_of_decision_11(self) -> None:
        assert [framework.value for framework in Framework] == [
            "arduino",
            "platformio",
            "esp_idf",
            "micropython",
            "other",
        ]

    @pytest.mark.parametrize("text", ["Arduino", "esp-idf", "circuitpython", ""])
    def test_refuses_any_other_value(self, text: str) -> None:
        with pytest.raises(ValueError, match="is not a valid Framework"):
            Framework(text)


type _PlainText = type[Description] | type[Changelog]

# Each plain text refuses with its own error, so the web marks the field it is about.
_REFUSAL: dict[_PlainText, type[InvalidDescriptionError | InvalidChangelogError]] = {
    Description: InvalidDescriptionError,
    Changelog: InvalidChangelogError,
}


@pytest.mark.parametrize("kind", [Description, Changelog])
class TestPlainText:
    def test_reads_crlf_and_a_bare_cr_as_a_line_feed(self, kind: _PlainText) -> None:
        assert kind("one\r\ntwo\rthree").value == "one\ntwo\nthree"

    def test_keeps_inner_line_breaks_and_trims_the_ends(self, kind: _PlainText) -> None:
        # Blank lines and indentation inside are the owner's layout: a changelog's list.
        text = "\n  Averages three readings.\n\n  - config.h: SAMPLES  \n\n"
        assert kind(text).value == "Averages three readings.\n\n  - config.h: SAMPLES"
        assert str(kind(text)) == kind(text).value

    def test_accepts_its_cap_and_refuses_one_character_more(self, kind: _PlainText) -> None:
        text = "x" * MAX_TEXT_LENGTH
        assert kind(text).value == text
        with pytest.raises(_REFUSAL[kind], match="between 1 and 4,000 characters"):
            kind(text + "x")

    def test_the_cap_counts_after_the_ends_are_trimmed(self, kind: _PlainText) -> None:
        text = "x" * MAX_TEXT_LENGTH
        assert kind(f"\r\n {text} \n").value == text

    @pytest.mark.parametrize("text", ["", "   ", "\r\n\t"])
    def test_blank_is_refused(self, kind: _PlainText, text: str) -> None:
        # The edge reads blank text as none before it gets here (requirements 1.6, 5.6).
        with pytest.raises(_REFUSAL[kind]):
            kind(text)
