"""A version's source files: each one's path and text, and the rules its files keep together.

Source is text kept in PostgreSQL (ADR 0006), byte for byte but for its line endings, so what
is copied back into the Arduino IDE compiles as it did. A path keeps to decision 9's rules,
which refuse what would break a path on Linux, macOS or Windows, though Windows still refuses
a device name such as `CON` and a part ending in a dot or a space, which they accept. Paths
compare by `lower()`, the folding the unique index uses. A version holds at most 100 files and
1,048,576 bytes of UTF-8.
"""

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from wiredex.firmware.domain.encoding import encodes
from wiredex.firmware.domain.errors import (
    InvalidPathError,
    NotTextError,
    PathTakenError,
    SourceFileNotFoundError,
    TooManyFilesError,
    VersionTooLargeError,
)
from wiredex.firmware.domain.values import SourceFileId

MAX_PATH_LENGTH = 200
MAX_FILES = 100  # in one version
MAX_VERSION_BYTES = 1_048_576  # ADR 0006's "e.g. 1 MB", counted in UTF-8

# The characters Windows refuses in a name, beside the controls and the two separators.
_RESERVED = frozenset('<>:"|?*')
# Parts of a path that name no file or folder: `a//b`, a trailing `/`, `./a`, `../a`.
_NOT_NAMES = frozenset({"", ".", ".."})


@dataclass(frozen=True, slots=True)
class SourcePath:
    """A file's name within its version, folders included: `weather_station.ino`,
    `src/sensor.cpp` (requirement 7.2). NFC, trimmed and `\\` read as `/`, then 1 to 200
    characters, starting inside the version, each part a name, with no control character, no
    half of a surrogate pair and none of `< > : " | ? *`. Its case is kept; `fold()` is what
    uniqueness compares."""

    value: str

    def __post_init__(self) -> None:
        path = unicodedata.normalize("NFC", self.value).strip().replace("\\", "/")
        if not 1 <= len(path) <= MAX_PATH_LENGTH:
            raise InvalidPathError(
                f"a path needs between 1 and {MAX_PATH_LENGTH} characters", item=self.value
            )
        fault = _path_fault(path)
        if fault is not None:
            raise InvalidPathError(f"{path!r} {fault}", item=self.value)
        object.__setattr__(self, "value", path)

    def fold(self) -> str:
        """What uniqueness compares: lower(), the unique index's own expression."""
        return self.value.lower()

    def folders(self) -> tuple[str, ...]:
        """The folders the path is in, folded, outermost first: `lib/bme/bme.h` is in `lib`
        and `lib/bme`."""
        parts = self.fold().split("/")
        return tuple("/".join(parts[:end]) for end in range(1, len(parts)))

    def is_sketch(self) -> bool:
        """An Arduino sketch, `.ino` in any case: a version lists these first, as the IDE
        opens its main tab first."""
        return self.fold().endswith(".ino")

    def __str__(self) -> str:
        return self.value


def _path_fault(path: str) -> str | None:
    """What requirement 7.2 refuses in a normalized path of the right length, and half of a
    surrogate pair, which PostgreSQL can't store; or None."""
    if path.startswith("/"):
        return "starts with /, but a path starts inside the version, like src/main.cpp"
    if not _NOT_NAMES.isdisjoint(path.split("/")):
        return "has an empty, . or .. part, which names no file or folder"
    if any(unicodedata.category(char) == "Cc" for char in path):
        return "holds a control character"
    if not encodes(path):
        return "holds half of a surrogate pair, which isn't valid Unicode"
    if not _RESERVED.isdisjoint(path):
        return 'holds one of < > : " | ? *, which Windows refuses in a name'
    return None


@dataclass(frozen=True, slots=True)
class SourceText:
    """A file's text exactly as typed but for its line endings: CRLF and a lone CR read as LF,
    since the Arduino IDE on Windows saves CRLF and one ending keeps copies and diffs clean.
    Tabs, trailing spaces, blank lines and a missing final line break are kept (requirement
    7.4). A NUL is refused, which PostgreSQL `text` can't hold and no text file does, and so is
    what UTF-8 can't encode, a lone surrogate from a JSON escape (requirement 7.5)."""

    value: str

    def __post_init__(self) -> None:
        text = self.value.replace("\r\n", "\n").replace("\r", "\n")
        if "\x00" in text:
            raise NotTextError("the text holds a NUL character, which a text file never does")
        if not encodes(text):
            raise NotTextError("the text holds half of a surrogate pair, which isn't valid Unicode")
        object.__setattr__(self, "value", text)

    @property
    def size(self) -> int:
        """Its bytes of UTF-8: what a version's limit counts."""
        return len(self.value.encode("utf-8"))

    @property
    def lines(self) -> int:
        """As an editor counts them: none in an empty file, and a last line whether or not a
        line break ends it."""
        breaks = self.value.count("\n")
        if not self.value or self.value.endswith("\n"):
            return breaks
        return breaks + 1

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SourceFile:
    """One file of a version. It has an id, so a rename keeps it (decision 10)."""

    id: SourceFileId
    path: SourcePath
    text: SourceText

    @classmethod
    def parse(cls, file_id: SourceFileId, path: str, text: str) -> SourceFile:
        """A file as a write sends it: its path read first, then its text, whose refusal names
        the file by its path as typed (requirement 7.5), since a batch sends several."""
        source_path = SourcePath(path)
        try:
            source_text = SourceText(text)
        except NotTextError as error:
            raise NotTextError(f"{source_path}: {error}", item=path) from error
        return cls(file_id, source_path, source_text)


@dataclass(frozen=True, slots=True)
class SourceFiles:
    """A version's files, in requirement 7.10's order: `.ino` files first, the Arduino IDE's
    main tab, then the rest, each group by folded path.

    Its rules (decision 9): no two paths equal ignoring case and no path another's folder, as
    no disk holds `lib` beside `lib/bme.h`; at most 100 files and 1,048,576 bytes. `of` checks
    them and orders the files, and `adding` and `replacing` go through the same check, so a
    write and a base's copy meet one set of limits; `without` can't break them.
    """

    items: tuple[SourceFile, ...] = ()

    @classmethod
    def of(cls, files: Iterable[SourceFile]) -> SourceFiles:
        """The files checked, then ordered. A clash of paths is `PathTakenError`, naming both
        paths, before `TooManyFilesError` and `VersionTooLargeError`."""
        return _checked(tuple(files), room=MAX_VERSION_BYTES)

    def adding(self, new: Sequence[SourceFile]) -> SourceFiles:
        """These files beside the others, all of them or none (requirement 7.1). The new ones
        are checked last, so a clash names the new file as the one typed."""
        return _checked((*self.items, *new), room=self.room)

    def replacing(self, file: SourceFile) -> SourceFiles:
        """The file's new path and text under its id: its own path and bytes don't count
        against it (requirement 7.8). `SourceFileNotFoundError` when no file has its id."""
        others = self.without(file.id)
        return _checked((*others.items, file), room=others.room)

    def without(self, file_id: SourceFileId) -> SourceFiles:
        """`SourceFileNotFoundError` for a file this version doesn't hold, another version's
        included (requirement 7.11)."""
        kept = tuple(held for held in self.items if held.id != file_id)
        if len(kept) == len(self.items):
            raise SourceFileNotFoundError("that file isn't in this version")
        return SourceFiles(kept)

    def get(self, file_id: SourceFileId) -> SourceFile | None:
        return next((held for held in self.items if held.id == file_id), None)

    @property
    def size(self) -> int:
        """The files' bytes of UTF-8, summed."""
        return sum(held.text.size for held in self.items)

    @property
    def room(self) -> int:
        """What is left of the version's 1,048,576 bytes, which a refusal says."""
        return MAX_VERSION_BYTES - self.size


def _checked(files: tuple[SourceFile, ...], room: int) -> SourceFiles:
    """Decision 9's rules over what a version would hold, in requirement 7.10's order. `room`
    is what the version had left before the write, for the size refusal to say (7.7)."""
    _ensure_apart(files)
    if len(files) > MAX_FILES:
        raise TooManyFilesError(f"a version holds at most {MAX_FILES} files, not {len(files)}")
    size = sum(file.text.size for file in files)
    if size > MAX_VERSION_BYTES:
        written = size - (MAX_VERSION_BYTES - room)
        raise VersionTooLargeError(
            f"{written:,} bytes won't fit: a version holds {MAX_VERSION_BYTES:,} bytes of "
            f"source, and this one has {room:,} left"
        )
    return SourceFiles(tuple(sorted(files, key=_listing_order)))


def _listing_order(file: SourceFile) -> tuple[bool, str]:
    """Sketches first, then the rest, each group by folded path: the folded paths are distinct
    by then, so the order is total."""
    return not file.path.is_sketch(), file.path.fold()


def _ensure_apart(files: Iterable[SourceFile]) -> None:
    """No two paths a disk can't hold side by side (requirement 7.3), checked in the order
    given, so a clash is named at the later file, the one being written, with the earlier."""
    paths: dict[str, SourcePath] = {}  # each folded path, to its path
    folders: dict[str, SourcePath] = {}  # each folded folder, to the first path inside it
    for file in files:
        held = _clashing(file.path, paths, folders)
        if held is not None:
            raise _taken(file.path, held)
        paths[file.path.fold()] = file.path
        for folder in file.path.folders():
            folders.setdefault(folder, file.path)


def _clashing(
    path: SourcePath, paths: Mapping[str, SourcePath], folders: Mapping[str, SourcePath]
) -> SourcePath | None:
    """The path held that this one clashes with: the same path, a path inside this one, or a
    path that is one of this one's folders."""
    folded = path.fold()
    held = paths.get(folded, folders.get(folded))
    if held is not None:
        return held
    return next((paths[folder] for folder in path.folders() if folder in paths), None)


def _taken(path: SourcePath, held: SourcePath) -> PathTakenError:
    """The refusal naming both paths; its item is the one being written."""
    if path == held:
        message = f"there is already a file {held}"
    elif path.fold() == held.fold():
        message = f"{path} and {held} are one path to Windows and macOS"
    elif path.fold() in held.folders():
        message = f"{path} is a folder of {held}, so it can't be a file too"
    else:
        message = f"{path} would be inside {held}, which is a file"
    return PathTakenError(message, item=str(path))
