from enum import StrEnum
from typing import ClassVar

from wiredex.firmware.domain.encoding import escaped


class FirmwareError(ValueError):
    """A value or change that breaks a firmware rule. The message is safe to show to users."""


class FirmwareNotFoundError(FirmwareError):
    """A firmware the workspace doesn't hold, another workspace's included: a 404 rather than a
    403, so an id says nothing about another bench (requirement 9.2)."""


class VersionNotFoundError(FirmwareError):
    """A version the workspace doesn't hold, or a version of another firmware named as a base
    (requirement 5.9)."""


class SourceFileNotFoundError(FirmwareError):
    """A file that isn't in the version it was named under, another version's included
    (requirement 7.11)."""


class RevisionNotFoundError(FirmwareError):
    """A revision the workspace doesn't hold, named to link, to start a firmware for or to read
    the firmware of (requirement 3.7). A linked revision that goes later isn't refused: reads
    leave it out and keep the link (decision 3)."""


class FirmwareField(StrEnum):
    """The field a refusal is about, which the browser marks (decision 13)."""

    NAME = "name"
    TARGET = "target"
    DESCRIPTION = "description"
    VERSION = "version"
    CHANGELOG = "changelog"
    PATH = "path"
    CONTENT = "content"
    FILES = "files"


class FirmwareRefusal(StrEnum):
    """Why a firmware write was refused, as a code the web translates (the design's Error
    Handling). The API answers the English sentence beside it, as projects' refusals do."""

    INVALID_NAME = "invalid_name"
    NAME_TAKEN = "name_taken"
    INVALID_TARGET = "invalid_target"
    INVALID_DESCRIPTION = "invalid_description"
    INVALID_VERSION = "invalid_version"
    VERSION_TAKEN = "version_taken"
    INVALID_CHANGELOG = "invalid_changelog"
    VERSION_RELEASED = "version_released"
    NO_FILES = "no_files"
    NO_CHANGELOG = "no_changelog"
    INVALID_PATH = "invalid_path"
    PATH_TAKEN = "path_taken"
    NOT_TEXT = "not_text"
    TOO_MANY_FILES = "too_many_files"
    VERSION_TOO_LARGE = "version_too_large"


class FirmwareRefusalError(FirmwareError):
    """A refused firmware write, with its code, its field and what it names.

    `code` and `field` are the leaf's own, so they live on the class, as projects'
    `ContentError` keeps them. `item` is the name, number or path as typed, which the browser
    shows beside the field (decision 13). The message and the item write half of a surrogate
    pair as its escape, `\\ud800`: typed text can hold one, from a JSON escape, and the answer
    carrying a refusal is UTF-8, which can't.
    """

    code: ClassVar[FirmwareRefusal]
    field: ClassVar[FirmwareField | None] = None

    def __init__(self, message: str, item: str | None = None) -> None:
        super().__init__(escaped(message))
        self.item = None if item is None else escaped(item)


class InvalidNameError(FirmwareRefusalError):
    """A name that is empty once trimmed and collapsed, longer than 120 characters or holding a
    control character (requirement 1.2): the list and a revision's section show it on one
    line. Half of a surrogate pair is refused too, which PostgreSQL can't store."""

    code = FirmwareRefusal.INVALID_NAME
    field = FirmwareField.NAME


class NameTakenError(FirmwareRefusalError):
    """A name another firmware of the workspace holds, ignoring case (requirement 1.3): the list
    and a revision's section would show two firmware alike. The message names the one holding
    it."""

    code = FirmwareRefusal.NAME_TAKEN
    field = FirmwareField.NAME


class InvalidTargetError(FirmwareRefusalError):
    """A board target that is empty once trimmed and collapsed, longer than 200 characters or
    holding a control character (requirement 1.4), or holding half of a surrogate pair, which
    PostgreSQL can't store. Its case is kept, since a toolchain reads `esp32:esp32:esp32` or
    `RPI_PICO` as it is spelled."""

    code = FirmwareRefusal.INVALID_TARGET
    field = FirmwareField.TARGET


class InvalidDescriptionError(FirmwareRefusalError):
    """A description longer than 4,000 characters once its ends are trimmed (requirement 1.6),
    or holding a NUL or half of a surrogate pair, which PostgreSQL can't store. A blank one
    isn't refused: it reads as none."""

    code = FirmwareRefusal.INVALID_DESCRIPTION
    field = FirmwareField.DESCRIPTION


class InvalidVersionError(FirmwareRefusalError):
    """A number requirement 5.1's SemVer grammar doesn't read: a leading zero, a word where a
    number goes, more than 64 characters, or build metadata, which is refused rather than
    dropped so the number kept is the one typed (decision 6). The message says what is wrong."""

    code = FirmwareRefusal.INVALID_VERSION
    field = FirmwareField.VERSION


class VersionTakenError(FirmwareRefusalError):
    """A number another version of the same firmware holds (requirement 5.2): a number written
    in a board's log has to name one version."""

    code = FirmwareRefusal.VERSION_TAKEN
    field = FirmwareField.VERSION


class InvalidChangelogError(FirmwareRefusalError):
    """A changelog longer than 4,000 characters once its ends are trimmed (requirement 5.6), or
    holding a NUL or half of a surrogate pair, which PostgreSQL can't store. A blank one isn't
    refused: it reads as none."""

    code = FirmwareRefusal.INVALID_CHANGELOG
    field = FirmwareField.CHANGELOG


class VersionReleasedError(FirmwareRefusalError):
    """A write to a released version's number, changelog or files, or releasing it again
    (requirements 6.4, 6.5): a number in a board's log always means the same code, so a change
    is a new version (decision 7). A 409: the request was fine, the version's state refuses
    it."""

    code = FirmwareRefusal.VERSION_RELEASED


class NoFilesError(FirmwareRefusalError):
    """Releasing a draft that holds no source file (requirement 6.2): a release is code to flash
    onto a board, and an empty one has none."""

    code = FirmwareRefusal.NO_FILES


class NoChangelogError(FirmwareRefusalError):
    """Releasing a draft with no changelog (requirement 6.3): a release is read later for what
    it changed, and one without a changelog is a number with no story (decision 7)."""

    code = FirmwareRefusal.NO_CHANGELOG
    field = FirmwareField.CHANGELOG


class InvalidPathError(FirmwareRefusalError):
    """A path that is empty once normalized or longer than 200 characters, starts with `/`,
    holds an empty, `.` or `..` segment, or holds a control character or one of
    `< > : " | ? *` (requirement 7.2), or half of a surrogate pair, which PostgreSQL can't
    store. What is left is what Linux, macOS and Windows can all hold, so every path can be
    written to disk as it is (decision 9). The item is the path as typed."""

    code = FirmwareRefusal.INVALID_PATH
    field = FirmwareField.PATH


class PathTakenError(FirmwareRefusalError):
    """A path another file of the version holds, ignoring case, one that names a folder of
    another file's path, or one whose folders include another file's path (requirement 7.3):
    no disk holds `lib` beside `lib/bme.h`, and Windows and macOS don't hold `Config.h` beside
    `config.h`. The message names both paths; the item is the one typed."""

    code = FirmwareRefusal.PATH_TAKEN
    field = FirmwareField.PATH


class NotTextError(FirmwareRefusalError):
    """Text holding a NUL, which PostgreSQL `text` can't store and no source file holds, or
    text that can't be encoded as UTF-8, such as a lone surrogate from a JSON escape
    (requirement 7.5, decision 9). The item is the file's path."""

    code = FirmwareRefusal.NOT_TEXT
    field = FirmwareField.CONTENT


class TooManyFilesError(FirmwareRefusalError):
    """A write that would leave a version holding more than 100 files (requirement 7.6). A
    version is a sketch, a handful of files: the cap keeps the page that lists them, and the
    check every write makes over them, bounded."""

    code = FirmwareRefusal.TOO_MANY_FILES
    field = FirmwareField.FILES


class VersionTooLargeError(FirmwareRefusalError):
    """A write that would take a version's files past 1,048,576 bytes of UTF-8, the cap ADR 0006
    puts on source kept in PostgreSQL (requirement 7.7). The message says how much room is
    left."""

    code = FirmwareRefusal.VERSION_TOO_LARGE
    field = FirmwareField.FILES
