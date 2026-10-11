"""Firmware's ids; a firmware's name, board target, framework, description and repository; a
version's changelog and commit.

A flash's own values, its unit's code and its notes, live with it in `flash.py`.

Each value normalizes what it is given and refuses, with its own error, what it can't hold, as
projects' values do. Blank text for a description or a changelog is no text at all: the edge
reads it as None before it gets here (requirements 1.6, 5.6).
"""

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import NewType
from uuid import UUID

from wiredex.firmware.domain.encoding import encodes
from wiredex.firmware.domain.errors import (
    FirmwareRefusalError,
    InvalidChangelogError,
    InvalidCommitError,
    InvalidDescriptionError,
    InvalidNameError,
    InvalidRepositoryError,
    InvalidTargetError,
)

# Firmware declares its own WorkspaceId, as every module does: modules don't import each
# other's domain.
WorkspaceId = NewType("WorkspaceId", UUID)
FirmwareId = NewType("FirmwareId", UUID)
VersionId = NewType("VersionId", UUID)
SourceFileId = NewType("SourceFileId", UUID)
# A revision of projects, by id alone: firmware holds no key into projects' tables (ADR 0001).
RevisionId = NewType("RevisionId", UUID)
# A unit of inventory, by id alone too: a flash names it with no key into inventory's tables
# (15-flash-log decision 1).
UnitId = NewType("UnitId", UUID)
FlashId = NewType("FlashId", UUID)

MAX_NAME_LENGTH = 120
MAX_TARGET_LENGTH = 200
MAX_TEXT_LENGTH = 4_000  # a firmware's description, a version's changelog
MAX_REPOSITORY_LENGTH = 500
MIN_COMMIT_LENGTH = 7  # what `git log --oneline` prints
MAX_COMMIT_LENGTH = 64  # a SHA-256 object name; a SHA-1 one has 40


class Framework(StrEnum):
    """What a firmware is written against (decision 11). It changes no rule; the browser shows
    its name and offers a first file's placeholder from it. A closed list, so the web has a word
    to translate for each and a later filter a value to match."""

    ARDUINO = "arduino"
    PLATFORMIO = "platformio"
    ESP_IDF = "esp_idf"
    MICROPYTHON = "micropython"
    OTHER = "other"


def _one_line(text: str, cap: int, what: str, error: type[FirmwareRefusalError]) -> str:
    """Trimmed and collapsed, then 1 to `cap` characters, no control character and no half of
    a surrogate pair.

    A tab or a line break is whitespace, collapsed before the check, so only controls that
    aren't whitespace are refused: NUL, a bell, DEL, and the like (Unicode's `Cc`). Half of a
    surrogate pair, which a JSON escape such as `\\ud800` gives Python, is refused because
    UTF-8, and so PostgreSQL, can't hold it.
    """
    collapsed = " ".join(text.split())
    if not 1 <= len(collapsed) <= cap:
        raise error(f"{what} needs between 1 and {cap} characters")
    if any(unicodedata.category(char) == "Cc" for char in collapsed):
        raise error(f"{what} can't hold a control character")
    if not encodes(collapsed):
        raise error(f"{what} can't hold half of a surrogate pair, which isn't valid Unicode")
    return collapsed


def _plain_text(text: str, what: str, error: type[FirmwareRefusalError]) -> str:
    """Line breaks are the owner's layout, so only their spelling is unified and the ends
    trimmed: a changelog pasted with CRLF and one typed read the same. What PostgreSQL can't
    store is refused: a NUL, which `text` can't hold, and half of a surrogate pair, which UTF-8
    can't encode."""
    unified = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not 1 <= len(unified) <= MAX_TEXT_LENGTH:
        raise error(f"{what} needs between 1 and {MAX_TEXT_LENGTH:,} characters")
    if "\x00" in unified:
        raise error(f"{what} can't hold a NUL character")
    if not encodes(unified):
        raise error(f"{what} can't hold half of a surrogate pair, which isn't valid Unicode")
    return unified


@dataclass(frozen=True, slots=True)
class FirmwareName:
    """1 to 120 characters, trimmed and collapsed, no control character or half of a surrogate
    pair, kept as cased (requirement 1.2). `fold()` is what the unique index compares."""

    value: str

    def __post_init__(self) -> None:
        name = _one_line(self.value, MAX_NAME_LENGTH, "a firmware name", InvalidNameError)
        object.__setattr__(self, "value", name)

    def fold(self) -> str:
        """What uniqueness compares: lower(), the unique index's own expression."""
        return self.value.lower()

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class BoardTarget:
    """An FQBN or a board name as its toolchain spells it, `esp32:esp32:esp32` or `RPI_PICO`:
    case kept, trimmed and collapsed, 1 to 200 characters, no control character
    (requirement 1.4) or half of a surrogate pair."""

    value: str

    def __post_init__(self) -> None:
        target = _one_line(self.value, MAX_TARGET_LENGTH, "a board target", InvalidTargetError)
        object.__setattr__(self, "value", target)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Description:
    """What a firmware is for: \\r\\n and \\r read as \\n, ends trimmed, line breaks kept, 1 to
    4,000 characters (requirement 1.6), no NUL or half of a surrogate pair."""

    value: str

    def __post_init__(self) -> None:
        text = _plain_text(self.value, "a description", InvalidDescriptionError)
        object.__setattr__(self, "value", text)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Changelog:
    """What a version changed, in the owner's words: the description's rules, with its own
    error (requirement 5.6)."""

    value: str

    def __post_init__(self) -> None:
        text = _plain_text(self.value, "a changelog", InvalidChangelogError)
        object.__setattr__(self, "value", text)

    def __str__(self) -> str:
        return self.value


# `git@github.com:owner/repo.git`, the address `git clone` takes over SSH.
_SCP_LIKE = re.compile(r"^[A-Za-z0-9._-]+@(?P<host>[A-Za-z0-9.-]+):(?P<path>[^\s:][^\s]*)$")
_WEB = re.compile(r"^(?P<scheme>https?)://(?P<host>[^/\s?#]+)(?P<path>/[^\s?#]*)?$", re.IGNORECASE)
_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::\d{1,5})?$")
_HEX = re.compile(r"^[0-9a-f]+$")


@dataclass(frozen=True, slots=True)
class Repository:
    """Where a firmware's code lives, as the address of the repository's page: `https://` or
    `http://`, a host and a path, at most 500 characters.

    Kept as a page to open, so what `git clone` takes is read into one: a trailing `.git` and
    slashes go, and `git@host:owner/repo.git` becomes `https://host/owner/repo`. An address with
    a user name or a password in it is refused rather than stored: a token pasted with the
    address would sit in the database, the history and every page that links to it.
    """

    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _repository(self.value.strip()))

    def __str__(self) -> str:
        return self.value


def _repository(typed: str) -> str:
    scp = _SCP_LIKE.match(typed)
    address = f"https://{scp['host']}/{scp['path']}" if scp else typed
    if not 1 <= len(address) <= MAX_REPOSITORY_LENGTH:
        raise InvalidRepositoryError(
            f"a repository address needs between 1 and {MAX_REPOSITORY_LENGTH} characters"
        )
    web = _WEB.match(address)
    if web is None:
        raise InvalidRepositoryError(
            "a repository is the address of its page, like https://github.com/owner/repo, "
            "with no question mark or # after it"
        )
    if "@" in web["host"]:
        raise InvalidRepositoryError(
            "a repository address can't carry a user name or a password: type it without "
            "what comes before the @"
        )
    if not _HOST.match(web["host"]):
        raise InvalidRepositoryError(f"{web['host']} isn't a host name")
    path = (web["path"] or "").rstrip("/").removesuffix(".git").rstrip("/")
    if not path:
        raise InvalidRepositoryError(
            "a repository address names the repository after the host, like "
            "https://github.com/owner/repo"
        )
    return f"{web['scheme'].lower()}://{web['host'].lower()}{path}"


@dataclass(frozen=True, slots=True)
class Commit:
    """The commit a version was built from, by its object name: 7 to 64 hexadecimal digits,
    kept lower-cased, whole or abbreviated as it was given. A name, not a branch or a tag: it
    has to point at the same code for as long as the version exists."""

    value: str

    def __post_init__(self) -> None:
        name = self.value.strip().lower()
        if not MIN_COMMIT_LENGTH <= len(name) <= MAX_COMMIT_LENGTH or not _HEX.match(name):
            raise InvalidCommitError(
                f"a commit is {MIN_COMMIT_LENGTH} to {MAX_COMMIT_LENGTH} of the digits 0-9 and "
                "a-f, as git log prints it; a branch or a tag moves, so it isn't one"
            )
        object.__setattr__(self, "value", name)

    def __str__(self) -> str:
        return self.value
