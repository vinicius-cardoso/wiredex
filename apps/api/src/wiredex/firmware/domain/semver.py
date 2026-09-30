"""Version numbers: SemVer 2.0.0 without build metadata, lower-cased (decision 6).

A number's canonical text is its identity, unique per firmware: `v1.2.0` and `1.2.0` are one
number, and so are `1.0.0-RC.1` and `1.0.0-rc.1`. Build metadata is refused rather than
dropped, since dropping what the owner typed would change it silently; and without it two
numbers of equal precedence are the same number, so the order is total.
"""

import re
from collections.abc import Collection
from dataclasses import dataclass, replace

from wiredex.firmware.domain.errors import InvalidVersionError

MAX_VERSION_LENGTH = 64

type Identifier = int | str

# Explicit ASCII classes: `\d` would take other scripts' digits, which int() reads too.
_NUMBER = r"0|[1-9][0-9]*"
# A letter or a hyphen somewhere, so an identifier of digits alone is always a number.
_WORD = r"[0-9]*[A-Za-z-][0-9A-Za-z-]*"
_IDENTIFIER = rf"(?:{_NUMBER}|{_WORD})"
_SEMVER = re.compile(
    rf"({_NUMBER})\.({_NUMBER})\.({_NUMBER})(?:-({_IDENTIFIER}(?:\.{_IDENTIFIER})*))?"
)
# The same shape with leading zeros allowed: text it reads and `_SEMVER` doesn't has a number
# starting with 0, which the refusal then says.
_WITH_LEADING_ZEROS = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?")
# A word as a number stores it: lower-cased, and never digits alone.
_STORED_WORD = re.compile(r"[0-9]*[a-z-][0-9a-z-]*")


def _is_number(value: object) -> bool:
    """A whole number from 0; `True` is refused, although Python counts it an int."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_identifier(value: object) -> bool:
    if isinstance(value, str):
        return _STORED_WORD.fullmatch(value) is not None
    return _is_number(value)


@dataclass(frozen=True, slots=True)
class SemVer:
    """A SemVer 2.0.0 number without build metadata, lower-cased (decision 6).

    Built from parts, it holds only what `parse` could read, so its text is its identity:
    numbers are whole and from 0, words are lower-case, and digits alone are never a word. The
    64-character cap is `parse`'s, on what is typed; `successor` never refuses, so the successor
    of a number within two characters of the cap can pass it.
    """

    major: int
    minor: int
    patch: int
    prerelease: tuple[Identifier, ...] = ()

    def __post_init__(self) -> None:
        core = (self.major, self.minor, self.patch)
        if not (all(map(_is_number, core)) and all(map(_is_identifier, self.prerelease))):
            raise InvalidVersionError(
                f"{self!r} is not a version number: its numbers are whole and from 0, its "
                "words lower-case and never digits alone"
            )

    @classmethod
    def parse(cls, text: str) -> SemVer:
        """Requirement 5.1's grammar: after trimming, an optional leading `v`, then
        `MAJOR.MINOR.PATCH` and an optional pre-release, at most 64 characters, kept
        lower-cased. `InvalidVersionError` says what is wrong and names the text as typed."""
        number = text.strip().removeprefix("v")
        # Checked before anything reads the digits: int() refuses thousands of them with an
        # error of its own.
        if len(number) > MAX_VERSION_LENGTH:
            raise InvalidVersionError(
                f"a version number has at most {MAX_VERSION_LENGTH} characters", item=text
            )
        read = _SEMVER.fullmatch(number)
        if read is None:
            raise _not_a_version(text, number)
        major, minor, patch, prerelease = read.groups()
        return cls(int(major), int(minor), int(patch), _identifiers(prerelease))

    def successor(self) -> SemVer:
        """The number after this one (requirement 5.4): with no pre-release, the patch plus
        one (1.2.0 → 1.2.1); with a numeric last identifier, that identifier plus one
        (1.3.0-rc.1 → 1.3.0-rc.2); otherwise `.1` appended (1.3.0-beta → 1.3.0-beta.1). Each
        is above this number, so the successor of the highest is never taken."""
        if not self.prerelease:
            return replace(self, patch=self.patch + 1)
        *head, last = self.prerelease
        if isinstance(last, int):
            return replace(self, prerelease=(*head, last + 1))
        return replace(self, prerelease=(*self.prerelease, 1))

    def precedence(self) -> tuple[object, ...]:
        """SemVer 2.0.0 §11 as a sort key: (major, minor, patch, release flag, identifiers),
        each identifier (0, n) when numeric and (1, text) otherwise.

        Tuples compare element by element, a shorter one first when the rest is equal. The
        flag, 0 for a pre-release and 1 for a release, puts 1.0.0-rc.1 before 1.0.0; (0, n)
        before (1, text) puts numeric identifiers before words, which compare in ASCII order.
        """
        release = 0 if self.prerelease else 1
        identifiers = tuple(
            (0, part) if isinstance(part, int) else (1, part) for part in self.prerelease
        )
        return (self.major, self.minor, self.patch, release, identifiers)

    def __lt__(self, other: object) -> bool:
        """By precedence. The order is total: two numbers of equal precedence are equal, since
        neither carries build metadata."""
        if not isinstance(other, SemVer):
            return NotImplemented
        return self.precedence() < other.precedence()

    def __str__(self) -> str:
        """The canonical text, `1.3.0-rc.1`: what a version is known and stored by."""
        core = f"{self.major}.{self.minor}.{self.patch}"
        if not self.prerelease:
            return core
        return core + "-" + ".".join(str(part) for part in self.prerelease)


# SemVer's own advice for a first development version.
FIRST_VERSION = SemVer(0, 1, 0)


def suggested_version(existing: Collection[SemVer]) -> SemVer:
    """The number a new version takes when none is typed (requirement 5.4): `FIRST_VERSION` for
    a firmware with none, else the successor of the highest, which is never taken."""
    if not existing:
        return FIRST_VERSION
    return max(existing).successor()


def _identifiers(prerelease: str | None) -> tuple[Identifier, ...]:
    """A pre-release's identifiers: digits alone as a number, anything else lower-cased."""
    if prerelease is None:
        return ()
    return tuple(int(part) if part.isdigit() else part.lower() for part in prerelease.split("."))


def _not_a_version(text: str, number: str) -> InvalidVersionError:
    """The refusal of text the grammar doesn't read, saying what is wrong with it: build
    metadata, a number starting with 0, or anything else."""
    core, plus, _ = number.partition("+")
    if plus and _SEMVER.fullmatch(core):
        reason = "carries build metadata after its +, which a version number can't: drop it"
    elif _WITH_LEADING_ZEROS.fullmatch(core):
        reason = "has a number with a leading zero, as 1.02.0 does, which SemVer doesn't allow"
    else:
        reason = "is not a version number like 1.2.0 or 1.3.0-rc.1"
    return InvalidVersionError(f"{text.strip()!r} {reason}", item=text)
