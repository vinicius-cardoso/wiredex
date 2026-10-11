import json

import pytest

from wiredex.firmware.domain.errors import (
    FirmwareField,
    FirmwareRefusalError,
    InvalidChangelogError,
    InvalidCommitError,
    InvalidDescriptionError,
    InvalidNameError,
    InvalidRepositoryError,
    InvalidTargetError,
)
from wiredex.firmware.domain.values import (
    MAX_NAME_LENGTH,
    MAX_TARGET_LENGTH,
    MAX_TEXT_LENGTH,
    BoardTarget,
    Changelog,
    Commit,
    Description,
    FirmwareName,
    Framework,
    Repository,
)

# Controls that aren't whitespace, so collapsing leaves them in place: NUL, a bell, DEL, and a
# C1 control (CSI) that a paste from a terminal can carry.
_CONTROLS = ["weather\x00station", "bell\x07", "del\x7f", "\x9b31m red"]
# What json.loads makes of "\ud800": a str Python holds and UTF-8, so PostgreSQL, can't.
_LONE_SURROGATE: str = json.loads('"\\ud800"')


def _encodes_in_utf_8(refused: FirmwareRefusalError) -> bool:
    """Whether the refusal's message and item encode, as the answer carrying them has to."""
    try:
        f"{refused}{refused.item or ''}".encode()
    except UnicodeEncodeError:
        return False
    return True


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

    @pytest.mark.parametrize(
        ("char", "reason"),
        [("\x00", "control character"), (_LONE_SURROGATE, "half of a surrogate pair")],
    )
    def test_what_postgresql_cant_store_is_refused_on_the_name(
        self, char: str, reason: str
    ) -> None:
        with pytest.raises(InvalidNameError, match=reason) as refused:
            FirmwareName(f"Weather {char}station")
        assert refused.value.field is FirmwareField.NAME
        assert _encodes_in_utf_8(refused.value)

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

    @pytest.mark.parametrize(
        ("char", "reason"),
        [("\x00", "control character"), (_LONE_SURROGATE, "half of a surrogate pair")],
    )
    def test_what_postgresql_cant_store_is_refused_on_the_target(
        self, char: str, reason: str
    ) -> None:
        with pytest.raises(InvalidTargetError, match=reason) as refused:
            BoardTarget(f"esp32:{char}esp32:esp32")
        assert refused.value.field is FirmwareField.TARGET
        assert _encodes_in_utf_8(refused.value)


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
_FIELD: dict[_PlainText, FirmwareField] = {
    Description: FirmwareField.DESCRIPTION,
    Changelog: FirmwareField.CHANGELOG,
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

    @pytest.mark.parametrize(
        ("char", "reason"),
        [("\x00", "NUL character"), (_LONE_SURROGATE, "half of a surrogate pair")],
    )
    def test_what_postgresql_cant_store_is_refused_on_its_own_field(
        self, kind: _PlainText, char: str, reason: str
    ) -> None:
        with pytest.raises(_REFUSAL[kind], match=reason) as refused:
            kind(f"Averages three\n{char}readings.")
        assert refused.value.field is _FIELD[kind]
        assert _encodes_in_utf_8(refused.value)


class TestRepository:
    @pytest.mark.parametrize(
        ("typed", "kept"),
        [
            ("https://github.com/vinicius/station", "https://github.com/vinicius/station"),
            ("  https://GitHub.com/vinicius/Station.git  ", "https://github.com/vinicius/Station"),
            ("https://gitlab.com/group/sub/station/", "https://gitlab.com/group/sub/station"),
            ("git@github.com:vinicius/station.git", "https://github.com/vinicius/station"),
            ("HTTP://gitea.local:3000/me/blink", "http://gitea.local:3000/me/blink"),
        ],
    )
    def test_is_kept_as_the_address_of_its_page(self, typed: str, kept: str) -> None:
        assert str(Repository(typed)) == kept

    @pytest.mark.parametrize(
        "typed",
        [
            "",
            "github.com/vinicius/station",
            "ftp://github.com/vinicius/station",
            "ssh://git@github.com/vinicius/station",
            "https://github.com",
            "https://github.com/",
            "https://github.com/.git",
            "https://github.com/vinicius/station?tab=readme",
            "https://github.com/vinicius/station#readme",
            "https://github.com/vinicius/my station",
            "https://-bad-/vinicius/station",
            "https://github.com/" + "x" * 500,
        ],
    )
    def test_refuses_what_isnt_one(self, typed: str) -> None:
        with pytest.raises(InvalidRepositoryError) as refused:
            Repository(typed)
        assert refused.value.field is FirmwareField.REPOSITORY

    @pytest.mark.parametrize(
        "typed",
        ["https://ghp_secret@github.com/me/blink", "https://me:hunter2@github.com/me/blink"],
    )
    def test_refuses_an_address_carrying_credentials_saying_what_to_remove(
        self, typed: str
    ) -> None:
        with pytest.raises(InvalidRepositoryError, match="before the @"):
            Repository(typed)


class TestCommit:
    @pytest.mark.parametrize(
        ("typed", "kept"),
        [
            ("a1b2c3d", "a1b2c3d"),
            (
                " 9FCEB02D0AE598E95DC970B74767F19372D61AF8\n",
                "9fceb02d0ae598e95dc970b74767f19372d61af8",
            ),
            ("a" * 64, "a" * 64),
        ],
    )
    def test_is_an_object_name_lower_cased(self, typed: str, kept: str) -> None:
        assert str(Commit(typed)) == kept

    @pytest.mark.parametrize("typed", ["", "a1b2c3", "main", "v1.0.0", "a1b2c3x", "a" * 65])
    def test_refuses_what_git_wouldnt_print(self, typed: str) -> None:
        with pytest.raises(InvalidCommitError) as refused:
            Commit(typed)
        assert refused.value.field is FirmwareField.COMMIT
