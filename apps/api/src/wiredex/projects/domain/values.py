import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import NewType
from uuid import UUID

from wiredex.projects.domain.errors import (
    InvalidProjectNameError,
    InvalidRevisionLabelError,
    InvalidSummaryError,
    InvalidTagError,
    InvalidTextError,
    ProjectsError,
    TooManyTagsError,
)

# Projects declares its own WorkspaceId, as every module does: modules don't import each
# other's domain.
WorkspaceId = NewType("WorkspaceId", UUID)
ProjectId = NewType("ProjectId", UUID)
RevisionId = NewType("RevisionId", UUID)
BomLineId = NewType("BomLineId", UUID)
NetId = NewType("NetId", UUID)
# A catalog part definition, as projects names it: a bare id with no foreign key, since
# modules don't point at each other's tables (decision 13).
PartId = NewType("PartId", UUID)
# Inventory's ids, as projects names them: bare uuids it only passes along to and from
# BuildStock, never a key into inventory's tables and never an import of its ids (ADR 0001,
# 10-build-lifecycle decision 15).
LotId = NewType("LotId", UUID)
UnitId = NewType("UnitId", UUID)
LocationId = NewType("LocationId", UUID)

MAX_PROJECT_NAME_LENGTH = 120
MAX_TEXT_LENGTH = 4_000  # a project's description, a revision's notes
MAX_SUMMARY_LENGTH = 120
MAX_TAG_LENGTH = 32
MAX_TAGS = 20
MAX_LABEL_LENGTH = 16


def _collapsed(text: str, cap: int, what: str, error: type[ProjectsError]) -> str:
    """Trims, collapses inner runs of whitespace, and refuses empty or over-long text."""
    collapsed = " ".join(text.split())
    if not 1 <= len(collapsed) <= cap:
        raise error(f"{what} needs between 1 and {cap} characters")
    return collapsed


def _plain_text(text: str, what: str) -> str:
    """Line breaks are the owner's layout, so only their spelling is unified and the ends
    trimmed: a pasted CRLF note and a typed one read the same."""
    unified = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not 1 <= len(unified) <= MAX_TEXT_LENGTH:
        raise InvalidTextError(f"{what} needs between 1 and {MAX_TEXT_LENGTH:,} characters")
    return unified


@dataclass(frozen=True, slots=True)
class ProjectName:
    """Trimmed, whitespace collapsed, 1-120 characters, kept as cased."""

    value: str

    def __post_init__(self) -> None:
        name = _collapsed(
            self.value, MAX_PROJECT_NAME_LENGTH, "a project name", InvalidProjectNameError
        )
        object.__setattr__(self, "value", name)

    def fold(self) -> str:
        """What uniqueness compares: lower(), the unique index's own expression."""
        return self.value.lower()

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Description:
    """Plain text: \\r\\n and \\r read as \\n, ends trimmed, line breaks kept, 1-4,000
    characters. Blank text is no description, which the edge reads as None before it gets
    here."""

    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _plain_text(self.value, "a description"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Notes:
    """A revision's notes: what changed, what to watch. The description's rules."""

    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _plain_text(self.value, "notes"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Summary:
    """A few words on what a revision is (breadboard): trimmed, collapsed, 1-120 characters."""

    value: str

    def __post_init__(self) -> None:
        summary = _collapsed(
            self.value, MAX_SUMMARY_LENGTH, "a revision summary", InvalidSummaryError
        )
        object.__setattr__(self, "value", summary)

    def __str__(self) -> str:
        return self.value


def _normalized_tag(text: str) -> str:
    # NFKC and lower() could each undo the other's work on some string (lower-casing İ adds a
    # combining dot), so the steps repeat until the text stops changing: a stored tag then
    # reads back as itself. No code point needs a second pass today; the bound is a guard.
    current = text
    for _ in range(4):
        step = " ".join(unicodedata.normalize("NFKC", current).lower().split())
        if step == current:
            break
        current = step
    return current


@dataclass(frozen=True, slots=True)
class Tag:
    """A word a project is filed under: NFKC, trimmed, whitespace collapsed, lower-cased,
    1-32 characters, no comma (the tag box splits on it) and no control character."""

    value: str

    def __post_init__(self) -> None:
        tag = _normalized_tag(self.value)
        if not 1 <= len(tag) <= MAX_TAG_LENGTH:
            raise InvalidTagError(
                f"the tag {self.value!r} needs between 1 and {MAX_TAG_LENGTH} characters"
            )
        if "," in tag:
            raise InvalidTagError(f"the tag {self.value!r} can't hold a comma")
        if any(unicodedata.category(char) == "Cc" for char in tag):
            raise InvalidTagError(f"the tag {self.value!r} can't hold a control character")
        object.__setattr__(self, "value", tag)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Tags:
    """A project's tags: each once, alphabetical, at most twenty (decision 8)."""

    values: tuple[Tag, ...]

    def __post_init__(self) -> None:
        # Normalized here rather than only in `of`, so no path stores a tag twice or out of
        # order, and two spellings of one set compare equal.
        distinct = tuple(sorted(set(self.values), key=lambda tag: tag.value))
        if len(distinct) > MAX_TAGS:
            raise TooManyTagsError(f"a project carries at most {MAX_TAGS} tags")
        object.__setattr__(self, "values", distinct)

    @classmethod
    def of(cls, texts: Iterable[str]) -> Tags:
        """Every text through `Tag`, then deduplicated and sorted; over 20 is refused."""
        return cls(tuple(Tag(text) for text in texts))

    @classmethod
    def none(cls) -> Tags:
        return cls(())

    def include(self, wanted: Tags) -> bool:
        """Whether every wanted tag is among these, what the list's tag filter asks."""
        return set(wanted.values) <= set(self.values)

    def texts(self) -> tuple[str, ...]:
        return tuple(tag.value for tag in self.values)


# ASCII only, so stepping and case folding have one answer; the ends are a letter or a
# digit, so the trailing run `successor` steps always exists.
_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
# The lazy prefix leaves the longest trailing run of digits, or else of letters, to step.
_TRAILING_RUN = re.compile(r"(.*?)([0-9]+|[A-Za-z]+)")
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _next_letters(letters: str) -> str:
    """Spreadsheet-column order: A → B, Z → AA, AZ → BA. Lower-case steps as lower-case;
    mixed case has no single case to keep, so it steps as capitals."""
    upper = letters.upper()
    stepped: list[str] = []
    carry = True
    for char in reversed(upper):
        if carry:
            carry = char == "Z"
            stepped.append("A" if carry else _ALPHABET[_ALPHABET.index(char) + 1])
        else:
            stepped.append(char)
    if carry:
        stepped.append("A")
    result = "".join(reversed(stepped))
    return result.lower() if letters.islower() else result


@dataclass(frozen=True, slots=True)
class RevisionLabel:
    """A revision's short name in its project: 1-16 ASCII letters, digits, '.', '-' or '_',
    starting and ending with a letter or a digit. Kept as typed, compared folded."""

    value: str

    def __post_init__(self) -> None:
        if len(self.value) > MAX_LABEL_LENGTH or not _LABEL.fullmatch(self.value):
            raise InvalidRevisionLabelError(
                f"{self.value!r} is not a label like A, v2 or 1.1: up to {MAX_LABEL_LENGTH} "
                "letters, digits, '.', '-' or '_', starting and ending with a letter or a digit"
            )

    @classmethod
    def first(cls) -> RevisionLabel:
        """`A`, a project's first revision (decision 2)."""
        return cls("A")

    def fold(self) -> str:
        return self.value.lower()

    def successor(self) -> RevisionLabel | None:
        """The next label in the owner's own scheme (decision 4): the trailing number up by
        one, keeping its width (v09 → v10, 1.9 → 1.10), or else the trailing letters one step
        on in spreadsheet-column order, in their case (A → B, Z → AA, rev-c → rev-d; letters
        of mixed case step as capitals). None when that would pass 16 characters, the only way
        a label runs out."""
        split = _TRAILING_RUN.fullmatch(self.value)
        assert split is not None  # noqa: S101  a valid label ends with a letter or a digit
        prefix, run = split.groups()
        stepped = str(int(run) + 1).zfill(len(run)) if run.isdigit() else _next_letters(run)
        following = prefix + stepped
        if len(following) > MAX_LABEL_LENGTH:
            return None
        return RevisionLabel(following)

    def __str__(self) -> str:
        return self.value


class RevisionStatus(StrEnum):
    """ADR 0003's four states. This spec writes only DRAFT; 10-build-lifecycle moves the rest.

    All four are named now, and the column's CHECK lists all four, so 10 adds transitions,
    not a migration (decision 5).
    """

    DRAFT = "draft"
    RESERVED = "reserved"
    BUILT = "built"
    DISMANTLED = "dismantled"

    @property
    def holds_stock(self) -> bool:
        """Reserved and built: a revision in them holds stock, so it can't be deleted and a
        recount or move against it is refused (10-build-lifecycle decision 7)."""
        return self in (RevisionStatus.RESERVED, RevisionStatus.BUILT)

    @property
    def deletable(self) -> bool:
        """Draft and dismantled: a revision in them holds nothing and can be deleted
        (requirements 9.1, 9.2). Over the four statuses this is `not holds_stock`, but both are
        stated so a status added later has to answer both."""
        return self in (RevisionStatus.DRAFT, RevisionStatus.DISMANTLED)
