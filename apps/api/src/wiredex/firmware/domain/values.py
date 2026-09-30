"""Firmware's ids; a firmware's name, board target, framework and description; a changelog.

Each value normalizes what it is given and refuses, with its own error, what it can't hold, as
projects' values do. Blank text for a description or a changelog is no text at all: the edge
reads it as None before it gets here (requirements 1.6, 5.6).
"""

import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import NewType
from uuid import UUID

from wiredex.firmware.domain.errors import (
    FirmwareRefusalError,
    InvalidChangelogError,
    InvalidDescriptionError,
    InvalidNameError,
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

MAX_NAME_LENGTH = 120
MAX_TARGET_LENGTH = 200
MAX_TEXT_LENGTH = 4_000  # a firmware's description, a version's changelog


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
    """Trimmed and collapsed, then 1 to `cap` characters and no control character.

    A tab or a line break is whitespace, collapsed before the check, so only controls that
    aren't whitespace are refused: NUL, a bell, DEL, and the like (Unicode's `Cc`).
    """
    collapsed = " ".join(text.split())
    if not 1 <= len(collapsed) <= cap:
        raise error(f"{what} needs between 1 and {cap} characters")
    if any(unicodedata.category(char) == "Cc" for char in collapsed):
        raise error(f"{what} can't hold a control character")
    return collapsed


def _plain_text(text: str, what: str, error: type[FirmwareRefusalError]) -> str:
    """Line breaks are the owner's layout, so only their spelling is unified and the ends
    trimmed: a changelog pasted with CRLF and one typed read the same."""
    unified = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not 1 <= len(unified) <= MAX_TEXT_LENGTH:
        raise error(f"{what} needs between 1 and {MAX_TEXT_LENGTH:,} characters")
    return unified


@dataclass(frozen=True, slots=True)
class FirmwareName:
    """1 to 120 characters, trimmed and collapsed, no control character, kept as cased
    (requirement 1.2). `fold()` is what the unique index compares."""

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
    (requirement 1.4)."""

    value: str

    def __post_init__(self) -> None:
        target = _one_line(self.value, MAX_TARGET_LENGTH, "a board target", InvalidTargetError)
        object.__setattr__(self, "value", target)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Description:
    """What a firmware is for: \\r\\n and \\r read as \\n, ends trimmed, line breaks kept, 1 to
    4,000 characters (requirement 1.6)."""

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
