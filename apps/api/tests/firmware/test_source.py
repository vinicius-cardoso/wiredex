import json
import re
import unicodedata
from functools import cache
from itertools import combinations
from uuid import UUID, uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.firmware.domain.errors import (
    FirmwareRefusalError,
    InvalidPathError,
    NotTextError,
    PathTakenError,
    SourceFileNotFoundError,
    TooManyFilesError,
    VersionTooLargeError,
)
from wiredex.firmware.domain.source import (
    MAX_FILES,
    MAX_PATH_LENGTH,
    MAX_VERSION_BYTES,
    SourceFile,
    SourceFiles,
    SourcePath,
    SourceText,
)
from wiredex.firmware.domain.values import SourceFileId

_RESERVED = '<>:"|?*'
# What json.loads makes of "\ud800": a str Python holds and UTF-8 can't encode.
_LONE_SURROGATE: str = json.loads('"\\ud800"')
_HALF = "x" * (MAX_VERSION_BYTES // 2)


def a_file(path: str, text: str = "") -> SourceFile:
    return SourceFile(SourceFileId(uuid7()), SourcePath(path), SourceText(text))


def _paths(files: SourceFiles) -> list[str]:
    return [str(file.path) for file in files.items]


def _encodes_in_utf_8(refused: FirmwareRefusalError) -> bool:
    """Whether the refusal's message and item encode, as the answer carrying them has to."""
    try:
        f"{refused}{refused.item or ''}".encode()
    except UnicodeEncodeError:
        return False
    return True


class TestSourcePath:
    @pytest.mark.parametrize(
        ("typed", "kept"),
        [
            ("weather_station.ino", "weather_station.ino"),
            ("  src/sensor.cpp \n", "src/sensor.cpp"),
            ("src\\sensor.cpp", "src/sensor.cpp"),  # as Windows writes it
            ("lib\\bme/bme280.h", "lib/bme/bme280.h"),
            ("e\u0301cran.h", "\u00e9cran.h"),  # decomposed, as macOS names files
            ("My Sketch/My Sketch.ino", "My Sketch/My Sketch.ino"),  # case and inner spaces
            (".clang-format", ".clang-format"),  # a name may start with a dot
            ("data/..config", "data/..config"),
        ],
    )
    def test_is_normalized_as_requirement_7_2_reads(self, typed: str, kept: str) -> None:
        assert SourcePath(typed).value == kept
        assert str(SourcePath(typed)) == kept

    def test_accepts_200_characters_and_refuses_201(self) -> None:
        path = "src/" + "x" * (MAX_PATH_LENGTH - len("src/"))
        assert SourcePath(path).value == path
        with pytest.raises(InvalidPathError, match="between 1 and 200 characters") as refused:
            SourcePath(path + "x")
        assert refused.value.item == path + "x"

    def test_the_cap_counts_the_normalized_path(self) -> None:
        # 200 é typed decomposed are 400 code points, and 200 once composed.
        typed = "e\u0301" * MAX_PATH_LENGTH
        assert SourcePath(f"  {typed}\t").value == "\u00e9" * MAX_PATH_LENGTH

    @pytest.mark.parametrize("typed", ["", "   ", "\t\n"])
    def test_blank_is_never_a_path(self, typed: str) -> None:
        with pytest.raises(InvalidPathError, match="between 1 and 200 characters") as refused:
            SourcePath(typed)
        assert refused.value.item == typed

    @pytest.mark.parametrize(
        ("typed", "reason"),
        [
            ("/sketch.ino", "starts with /"),
            ("\\sketch.ino", "starts with /"),
            ("src//main.cpp", "has an empty, . or .. part"),
            ("src/", "has an empty, . or .. part"),
            ("./sketch.ino", "has an empty, . or .. part"),
            ("src/../sketch.ino", "has an empty, . or .. part"),
            ("..", "has an empty, . or .. part"),
            ("sketch\t2.ino", "holds a control character"),
            ("sketch\n.ino", "holds a control character"),
            ("nul\x00.h", "holds a control character"),
            ("del\x7f.h", "holds a control character"),
            ("csi\x9b.h", "holds a control character"),  # a C1 control, from a terminal
            ("C:\\sketch.ino", "holds one of"),  # a Windows drive
        ],
    )
    def test_refuses_what_no_disk_holds_naming_it_as_typed(self, typed: str, reason: str) -> None:
        with pytest.raises(InvalidPathError, match=re.escape(reason)) as refused:
            SourcePath(typed)
        assert refused.value.item == typed

    @pytest.mark.parametrize("char", list(_RESERVED))
    def test_refuses_what_windows_refuses_in_a_name(self, char: str) -> None:
        with pytest.raises(InvalidPathError, match="Windows refuses") as refused:
            SourcePath(f"src/main{char}.cpp")
        assert refused.value.item == f"src/main{char}.cpp"

    @pytest.mark.parametrize(
        ("typed", "reason", "item"),
        [
            (f"src/main{_LONE_SURROGATE}.cpp", "half of a surrogate pair", "src/main\\ud800.cpp"),
            (f"/{_LONE_SURROGATE}.h", "starts with /", "/\\ud800.h"),
            (
                "x" * MAX_PATH_LENGTH + _LONE_SURROGATE,
                "between 1 and 200 characters",
                "x" * MAX_PATH_LENGTH + "\\ud800",
            ),
        ],
    )
    def test_names_half_of_a_surrogate_pair_by_its_escape(
        self, typed: str, reason: str, item: str
    ) -> None:
        # UTF-8, and so PostgreSQL and the answer carrying the refusal, can't hold one.
        with pytest.raises(InvalidPathError, match=reason) as refused:
            SourcePath(typed)
        assert refused.value.item == item
        assert _encodes_in_utf_8(refused.value)

    def test_folds_as_the_unique_index_does_and_keeps_its_case(self) -> None:
        assert SourcePath("Src/Config.H").fold() == "src/config.h"
        assert SourcePath("Src/Config.H").value == "Src/Config.H"

    @pytest.mark.parametrize(
        ("path", "folders"),
        [
            ("sketch.ino", ()),
            ("lib/bme.h", ("lib",)),
            ("Lib/BME/bme.h", ("lib", "lib/bme")),
        ],
    )
    def test_names_its_folders_folded_outermost_first(
        self, path: str, folders: tuple[str, ...]
    ) -> None:
        assert SourcePath(path).folders() == folders

    @pytest.mark.parametrize(
        ("path", "sketch"),
        [
            ("blink.ino", True),
            ("BLINK.INO", True),
            ("examples/fade/fade.ino", True),
            ("blink.ino.h", False),
            ("ino", False),
            ("main.cpp", False),
        ],
    )
    def test_a_sketch_ends_in_ino_in_any_case(self, path: str, sketch: bool) -> None:
        assert SourcePath(path).is_sketch() is sketch


class TestSourceText:
    @pytest.mark.parametrize(
        ("typed", "kept"),
        [
            ("a;\r\nb;\r\n", "a;\nb;\n"),  # CRLF, as the Arduino IDE on Windows saves
            ("a;\rb;\r", "a;\nb;\n"),  # a lone CR
            ("a;\r\r\nb;", "a;\n\nb;"),  # a lone CR, then a CRLF
            ("\n\r\n\r", "\n\n\n"),
        ],
    )
    def test_reads_crlf_and_a_lone_cr_as_lf(self, typed: str, kept: str) -> None:
        assert SourceText(typed).value == kept

    def test_keeps_everything_else_as_typed(self) -> None:
        # Tabs, trailing spaces, blank lines, a form feed, a BOM, and no final line break.
        text = "\ufeff#include <Wire.h>\t \n\n\n\tWire.begin();   \n\f// é µ 😀"
        assert SourceText(text).value == text
        assert str(SourceText(text)) == text

    def test_an_empty_file_is_text(self) -> None:
        assert (SourceText("").value, SourceText("").size, SourceText("").lines) == ("", 0, 0)

    def test_a_nul_is_refused(self) -> None:
        with pytest.raises(NotTextError, match="NUL character"):
            SourceText("int pin = 21;\x00")

    def test_a_lone_surrogate_is_refused(self) -> None:
        with pytest.raises(NotTextError, match="half of a surrogate pair"):
            SourceText(f"// {_LONE_SURROGATE}\n")

    @pytest.mark.parametrize(
        ("text", "size"),
        [("", 0), ("a", 1), ("é", 2), ("€", 3), ("😀", 4), ("a\r\nb", 3)],
    )
    def test_its_size_is_its_length_in_utf_8(self, text: str, size: int) -> None:
        assert SourceText(text).size == size

    @pytest.mark.parametrize(
        ("text", "lines"),
        [("a", 1), ("a\n", 1), ("\n", 1), ("a\nb", 2), ("a\n\n", 2), ("a\r\nb\r\n", 2)],
    )
    def test_counts_lines_as_an_editor_does(self, text: str, lines: int) -> None:
        assert SourceText(text).lines == lines


class TestSourceFile:
    def test_parse_reads_its_path_and_its_text(self) -> None:
        file_id = SourceFileId(uuid7())

        file = SourceFile.parse(file_id, " src\\main.cpp ", "int main() {}\r\n")

        assert file == SourceFile(
            file_id, SourcePath("src/main.cpp"), SourceText("int main() {}\n")
        )

    def test_parse_refuses_a_path_naming_it_as_typed(self) -> None:
        with pytest.raises(InvalidPathError) as refused:
            SourceFile.parse(SourceFileId(uuid7()), "../sketch.ino", "\x00")
        assert refused.value.item == "../sketch.ino"

    @pytest.mark.parametrize("text", ["\x00", _LONE_SURROGATE])
    def test_parse_refuses_what_isnt_text_naming_the_file(self, text: str) -> None:
        with pytest.raises(NotTextError) as refused:
            SourceFile.parse(SourceFileId(uuid7()), " lib\\bme.h", f"#pragma once\n{text}")
        assert refused.value.item == " lib\\bme.h"
        assert str(refused.value).startswith("lib/bme.h: the text holds")


class TestSourceFiles:
    def test_lists_sketches_first_then_the_rest_each_by_folded_path(self) -> None:
        paths = ("src/main.cpp", "config_b.h", "Config.h", "b.ino", "A.INO", "zeta.ino")

        files = SourceFiles.of(a_file(path) for path in paths)

        assert _paths(files) == [
            "A.INO",
            "b.ino",
            "zeta.ino",
            "Config.h",
            "config_b.h",
            "src/main.cpp",
        ]

    def test_an_empty_version_has_all_its_room(self) -> None:
        assert SourceFiles.of([]) == SourceFiles()
        assert (SourceFiles().size, SourceFiles().room) == (0, MAX_VERSION_BYTES)

    def test_the_same_path_twice_is_refused(self) -> None:
        with pytest.raises(PathTakenError) as refused:
            SourceFiles.of([a_file("config.h"), a_file("config.h")])
        assert str(refused.value) == "there is already a file config.h"
        assert refused.value.item == "config.h"

    def test_a_path_held_in_another_case_is_refused_naming_both(self) -> None:
        with pytest.raises(PathTakenError) as refused:
            SourceFiles.of([a_file("config.h"), a_file("Config.h")])
        assert str(refused.value) == "Config.h and config.h are one path to Windows and macOS"
        assert refused.value.item == "Config.h"

    def test_lib_beside_lib_bme_h_is_refused_whichever_comes_first(self) -> None:
        with pytest.raises(PathTakenError) as refused:
            SourceFiles.of([a_file("lib/bme.h"), a_file("lib")])
        assert str(refused.value) == "lib is a folder of lib/bme.h, so it can't be a file too"
        assert refused.value.item == "lib"

        with pytest.raises(PathTakenError) as refused:
            SourceFiles.of([a_file("lib"), a_file("lib/bme.h")])
        assert str(refused.value) == "lib/bme.h would be inside lib, which is a file"
        assert refused.value.item == "lib/bme.h"

    def test_a_folder_clashes_with_a_file_in_another_case(self) -> None:
        with pytest.raises(PathTakenError, match=re.escape("LIB/bme.h would be inside lib")):
            SourceFiles.of([a_file("lib"), a_file("LIB/bme.h")])

    def test_files_may_share_a_folder(self) -> None:
        files = SourceFiles.of(
            [a_file("lib/bme.h"), a_file("LIB/bme.cpp"), a_file("lib/bme/extra.h")]
        )
        assert _paths(files) == ["LIB/bme.cpp", "lib/bme.h", "lib/bme/extra.h"]

    def test_holds_100_files_and_refuses_a_101st(self) -> None:
        files = SourceFiles.of(a_file(f"file_{index}.h") for index in range(MAX_FILES - 1))

        full = files.adding([a_file("the_100th.h")])

        assert len(full.items) == MAX_FILES
        with pytest.raises(TooManyFilesError, match="at most 100 files, not 101"):
            full.adding([a_file("the_101st.h")])

    def test_holds_1048576_bytes_and_refuses_one_more(self) -> None:
        files = SourceFiles.of([a_file("a.h", _HALF), a_file("b.h", _HALF)])
        assert (files.size, files.room) == (MAX_VERSION_BYTES, 0)

        with pytest.raises(VersionTooLargeError) as refused:
            SourceFiles.of([a_file("a.h", _HALF), a_file("b.h", _HALF + "x")])
        assert str(refused.value) == (
            "1,048,577 bytes won't fit: a version holds 1,048,576 bytes of source, and this "
            "one has 1,048,576 left"
        )

    def test_counts_bytes_of_utf_8_not_characters(self) -> None:
        # Half the limit in characters, and all of it in bytes.
        files = SourceFiles.of([a_file("a.h", "é" * (MAX_VERSION_BYTES // 2))])
        assert files.room == 0
        with pytest.raises(VersionTooLargeError):
            files.adding([a_file("b.h", "x")])

    def test_adding_puts_the_new_files_in_their_place(self) -> None:
        config = a_file("config.h")
        sketch, sensor = a_file("sketch.ino"), a_file("src/sensor.cpp")

        files = SourceFiles.of([config]).adding([sensor, sketch])

        assert files.items == (sketch, config, sensor)

    def test_adding_refuses_the_batch_naming_the_new_file(self) -> None:
        files = SourceFiles.of([a_file("config.h")])
        with pytest.raises(PathTakenError) as refused:
            files.adding([a_file("sketch.ino"), a_file("CONFIG.H")])
        assert refused.value.item == "CONFIG.H"
        assert _paths(files) == ["config.h"]

    def test_adding_says_how_much_room_the_version_has_left(self) -> None:
        files = SourceFiles.of([a_file("sketch.ino", "x" * 1_000_000)])
        with pytest.raises(VersionTooLargeError) as refused:
            files.adding([a_file("a.h", "x" * 40_000), a_file("b.h", "x" * 10_000)])
        assert str(refused.value) == (
            "50,000 bytes won't fit: a version holds 1,048,576 bytes of source, and this one "
            "has 48,576 left"
        )

    def test_replacing_keeps_the_id_and_frees_its_own_path(self) -> None:
        config, sketch = a_file("config.h", "#define SDA 21"), a_file("sketch.ino")
        renamed = SourceFile(config.id, SourcePath("Config.h"), SourceText("#define SDA 22"))

        files = SourceFiles.of([config, sketch]).replacing(renamed)

        assert files.items == (sketch, renamed)
        assert files.get(config.id) == renamed

    def test_replacing_refuses_another_files_path_naming_it(self) -> None:
        config, sketch = a_file("config.h"), a_file("sketch.ino")
        files = SourceFiles.of([config, sketch])
        with pytest.raises(PathTakenError) as refused:
            files.replacing(SourceFile(config.id, SourcePath("Sketch.ino"), config.text))
        assert str(refused.value) == "Sketch.ino and sketch.ino are one path to Windows and macOS"
        assert refused.value.item == "Sketch.ino"

    def test_replacing_counts_the_files_old_bytes_as_room(self) -> None:
        small = a_file("small.h", "x" * 10)
        files = SourceFiles.of([a_file("big.h", "x" * (MAX_VERSION_BYTES - 10)), small])

        grown = files.replacing(SourceFile(small.id, small.path, SourceText("y" * 10)))

        assert grown.room == 0
        with pytest.raises(VersionTooLargeError, match="and this one has 10 left"):
            files.replacing(SourceFile(small.id, small.path, SourceText("y" * 11)))

    def test_without_removes_the_file_and_frees_its_path(self) -> None:
        lib = a_file("lib")
        files = SourceFiles.of([lib, a_file("sketch.ino")]).without(lib.id)

        assert _paths(files) == ["sketch.ino"]
        assert _paths(files.adding([a_file("lib/bme.h")])) == ["sketch.ino", "lib/bme.h"]

    def test_a_file_it_doesnt_hold_is_not_found(self) -> None:
        files = SourceFiles.of([a_file("sketch.ino")])
        elsewhere = a_file("config.h")

        assert files.get(elsewhere.id) is None
        with pytest.raises(SourceFileNotFoundError):
            files.replacing(elsewhere)
        with pytest.raises(SourceFileNotFoundError):
            files.without(elsewhere.id)


# --- Property 4: paths normalize once and stay safe ----------------------------------------

# Characters the rules treat specially, and ones NFC changes: separators, dots, whitespace,
# controls, a decomposed é, and the angstrom sign, which NFC reads as a letter A with a ring.
_PATH_TRICKY = "/\\. \t\n\x00\x7f\x85\u3000aAe\u0301\u212b" + _RESERVED
# Pieces of a name the rules accept, some of which NFC composes.
_NAME_PIECES = [*"abzAZ09_-.+#()", "é", "e\u0301", "\u212b", "µ", "😀"]
_NAMES = (
    st.lists(st.sampled_from(_NAME_PIECES), min_size=1, max_size=8)
    .map("".join)
    .filter(lambda name: name not in {".", ".."})
)


@st.composite
def _typed_paths(draw: st.DrawFn) -> tuple[str, str]:
    """A path the rules accept as the owner might type it, and the path it reads as: its names
    as drawn or decomposed, with `\\` for some of its slashes and whitespace around it."""
    names = draw(st.lists(_NAMES, min_size=1, max_size=4))
    typed = names[0]
    for name in names[1:]:
        typed += draw(st.sampled_from("/\\")) + name
    if draw(st.booleans()):
        typed = unicodedata.normalize("NFD", typed)
    padding = draw(st.sampled_from(["", " ", "\t", "\n ", "\u3000"]))
    return f"{padding}{typed}{padding}", unicodedata.normalize("NFC", "/".join(names))


def _accepted_path(text: str) -> SourcePath | None:
    try:
        return SourcePath(text)
    except InvalidPathError:
        return None


def _check_safe(path: SourcePath) -> None:
    value = path.value
    assert SourcePath(value) == path
    assert value == unicodedata.normalize("NFC", value)
    assert 1 <= len(value) <= MAX_PATH_LENGTH
    assert not value.startswith("/")
    assert "\\" not in value
    assert all(part not in {"", ".", ".."} for part in value.split("/"))
    assert all(unicodedata.category(char) != "Cc" for char in value)
    assert set(_RESERVED).isdisjoint(value)


@given(text=st.text() | st.text(alphabet=_PATH_TRICKY, max_size=24), typed=_typed_paths())
def test_paths_normalize_once_and_stay_safe(text: str, typed: tuple[str, str]) -> None:
    """Property 4: paths normalize once and stay safe.

    For any text SourcePath accepts, normalizing its value again gives the same path, and it
    has no empty, . or .. segment, no leading /, no \\, no control character and none of
    < > : " | ? *. The texts are drawn at random, from characters the rules treat specially,
    and as spellings of a path the rules accept: composed or decomposed, with \\ for some
    slashes and whitespace around it, which read as that path.

    **Validates: Requirements 7.2**
    """
    accepted = _accepted_path(text)
    if accepted is not None:
        assert accepted.value == unicodedata.normalize("NFC", text).strip().replace("\\", "/")
        _check_safe(accepted)
    spelling, expected = typed
    path = SourcePath(spelling)
    assert path.value == expected
    _check_safe(path)


# --- Property 5: text keeps everything but line endings ------------------------------------

# Line endings in every arrangement, beside what a file keeps: tabs, spaces, other scripts,
# and line separators that aren't a line feed.
_LINE_TRICKY = "\r\n\t x;é😀\u2028\x85\f"
_NOT_TEXT = st.sampled_from(["\x00", _LONE_SURROGATE, json.loads('"\\udfff"')])
_texts = (
    st.text()
    | st.text(alphabet=_LINE_TRICKY)
    | st.tuples(st.text(alphabet=_LINE_TRICKY), _NOT_TEXT, st.text()).map("".join)
)


def _has_surrogate(text: str) -> bool:
    return any("\ud800" <= char <= "\udfff" for char in text)


@given(text=_texts)
def test_text_keeps_everything_but_line_endings(text: str) -> None:
    """Property 5: text keeps everything but line endings.

    For any text SourceText accepts, its value is the text with CRLF and CR replaced by LF,
    applying it again changes nothing, and size is the value's UTF-8 length. The texts are
    drawn at random, from line endings in every arrangement, and with a NUL or half of a
    surrogate pair inside, which alone are refused.

    **Validates: Requirements 7.4, 7.5**
    """
    try:
        kept = SourceText(text)
    except NotTextError:
        assert "\x00" in text or _has_surrogate(text)
        return
    assert kept.value == text.replace("\r\n", "\n").replace("\r", "\n")
    assert SourceText(kept.value) == kept
    assert "\x00" not in kept.value
    assert kept.size == len(kept.value.encode("utf-8"))


# --- Property 6: a version's files stay within their limits, in order ----------------------

# Paths that clash in case and as folders, so that a handful of them often do, and some that
# clash with none, so that others don't.
_PATH_POOL = [
    "sketch.ino",
    "Sketch.INO",
    "b.ino",
    "config.h",
    "Config.h",
    "lib",
    "lib/bme.h",
    "LIB/bme280.cpp",
    "lib/bme",
    "lib/bme/extra.h",
    "src",
    "src/main.cpp",
    "main.py",
    "boot.py",
    "README.md",
]
# Sizes around the limit: two halves fill it, one byte more passes it, and so does a full
# file beside any other.
_SIZES = [
    0,
    1,
    17,
    MAX_VERSION_BYTES // 3,
    MAX_VERSION_BYTES // 2,
    MAX_VERSION_BYTES // 2 + 1,
    MAX_VERSION_BYTES,
]


@cache
def _text_of(size: int) -> SourceText:
    return SourceText("x" * size)


_few_files = st.lists(
    st.builds(
        SourceFile,
        st.uuids().map(SourceFileId),
        st.sampled_from(_PATH_POOL).map(SourcePath),
        st.sampled_from(_SIZES).map(_text_of),
    ),
    max_size=6,
)


@st.composite
def _many_files(draw: st.DrawFn) -> list[SourceFile]:
    """About a version's 100 files, a few of them sketches, with some from the pool, in any
    order."""
    count = draw(st.integers(MAX_FILES - 3, MAX_FILES + 2))
    files = [
        SourceFile(
            SourceFileId(UUID(int=index)),
            SourcePath(f"file_{index}.{'ino' if index % 10 == 0 else 'h'}"),
            _text_of(1),
        )
        for index in range(count)
    ]
    return draw(st.permutations(files + draw(_few_files)))


def _clash(first: str, second: str) -> bool:
    """Two folded paths no disk holds side by side: equal, or one a folder of the other."""
    return first == second or second.startswith(f"{first}/") or first.startswith(f"{second}/")


def _first_clash(files: list[SourceFile]) -> tuple[int, list[int]] | None:
    """The first file that clashes with an earlier one, and the earlier ones it clashes with."""
    folded = [file.path.fold() for file in files]
    for later in range(len(files)):
        earlier = [index for index in range(later) if _clash(folded[index], folded[later])]
        if earlier:
            return later, earlier
    return None


def _broken_rule(files: list[SourceFile]) -> type[FirmwareRefusalError] | None:
    """The first rule the files break, in the order `of` checks them: paths, count, bytes."""
    if _first_clash(files) is not None:
        return PathTakenError
    if len(files) > MAX_FILES:
        return TooManyFilesError
    if sum(file.text.size for file in files) > MAX_VERSION_BYTES:
        return VersionTooLargeError
    return None


def _check_within_limits(listed: SourceFiles, files: list[SourceFile]) -> None:
    folded = [file.path.fold() for file in listed.items]
    assert not any(_clash(first, second) for first, second in combinations(folded, 2))
    assert len(listed.items) <= MAX_FILES
    assert listed.size == sum(file.text.size for file in files) <= MAX_VERSION_BYTES
    assert listed.room == MAX_VERSION_BYTES - listed.size
    reference = sorted(
        files, key=lambda file: (not file.path.fold().endswith(".ino"), file.path.fold())
    )
    assert list(listed.items) == reference


def _check_names_both(refused: FirmwareRefusalError, files: list[SourceFile]) -> None:
    clash = _first_clash(files)
    assert clash is not None
    later, earlier = clash
    typed = str(files[later].path)
    assert refused.item == typed
    assert typed in str(refused)
    assert any(str(files[index].path) in str(refused) for index in earlier)


@given(files=_few_files | _many_files())
def test_a_versions_files_stay_within_their_limits_in_order(files: list[SourceFile]) -> None:
    """Property 6: a version's files stay within their limits, in order.

    For any files SourceFiles.of accepts, folded paths are distinct, no path is another's
    folder, there are at most 100 files and 1,048,576 bytes, and the order is .ino first, then
    by folded path; files breaking a rule are refused with that rule's error. The paths come
    from a pool that clashes in case and as folders; there are a handful of files, some big
    enough that two fill a version, or about a hundred, in any order. Files breaking several
    rules are refused for the first that of checks: paths, then the count, then the bytes; a
    clash is named at the later file, as the one typed, with one it clashes with.

    **Validates: Requirements 7.3, 7.6, 7.7, 7.10**
    """
    rule = _broken_rule(files)
    if rule is None:
        _check_within_limits(SourceFiles.of(files), files)
        return
    with pytest.raises(rule) as refused:
        SourceFiles.of(files)
    if rule is PathTakenError:
        _check_names_both(refused.value, files)
