import re
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import NewType
from uuid import UUID

from wiredex.identity.domain.errors import (
    InvalidEmailError,
    InvalidLifetimeError,
    InvalidNameError,
    WeakPasswordError,
)

UserId = NewType("UserId", UUID)
WorkspaceId = NewType("WorkspaceId", UUID)
SessionId = NewType("SessionId", UUID)

# Deliberately loose: one @, something on each side, a dot in the domain. Real
# validation is whether mail arrives, and Wiredex never sends any.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL_LENGTH = 254


@dataclass(frozen=True, slots=True)
class Email:
    """An email address, stored lower-cased so lookups and uniqueness ignore case."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if len(normalized) > MAX_EMAIL_LENGTH or not _EMAIL.match(normalized):
            raise InvalidEmailError(f"{self.value!r} is not an email address")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Name:
    """A person's or a workspace's display name: 1 to 80 characters, trimmed."""

    value: str

    def __post_init__(self) -> None:
        trimmed = " ".join(self.value.split())
        if not 1 <= len(trimmed) <= 80:  # noqa: PLR2004  the rule itself
            raise InvalidNameError("a name needs between 1 and 80 characters")
        object.__setattr__(self, "value", trimmed)

    def __str__(self) -> str:
        return self.value


MIN_PASSWORD_LENGTH = 12
# Hashing cost grows with input length; a cap keeps one request from hogging the CPU.
MAX_PASSWORD_LENGTH = 1024


@dataclass(frozen=True, slots=True)
class Password:
    """A plain-text password on its way to being hashed or checked. Never stored or shown."""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not MIN_PASSWORD_LENGTH <= len(self.value) <= MAX_PASSWORD_LENGTH:
            raise WeakPasswordError(
                f"a password needs between {MIN_PASSWORD_LENGTH} and "
                f"{MAX_PASSWORD_LENGTH} characters"
            )

    def __repr__(self) -> str:
        return "Password(***)"


_LIFETIME = re.compile(r"^(\d+)([hdw])$")
_LIFETIME_UNITS = {"h": timedelta(hours=1), "d": timedelta(days=1), "w": timedelta(weeks=1)}
MIN_GUEST_LIFETIME = timedelta(hours=1)
MAX_GUEST_LIFETIME = timedelta(days=90)


@dataclass(frozen=True, slots=True)
class GuestLifetime:
    """How long a guest account works: from an hour to 90 days."""

    value: timedelta

    def __post_init__(self) -> None:
        if not MIN_GUEST_LIFETIME <= self.value <= MAX_GUEST_LIFETIME:
            raise InvalidLifetimeError("a guest account lasts from 1 hour to 90 days")

    @classmethod
    def parse(cls, text: str) -> GuestLifetime:
        """Reads "12h", "7d" or "2w"."""
        match = _LIFETIME.match(text.strip().lower())
        if match is None:
            raise InvalidLifetimeError(f"{text!r} is not a duration like 12h, 7d or 2w")
        return cls(int(match[1]) * _LIFETIME_UNITS[match[2]])


@dataclass(frozen=True, slots=True)
class PasswordHash:
    """An already-hashed password. Hashing and checking live behind a port (step 3)."""

    value: str

    def __repr__(self) -> str:
        return "PasswordHash(***)"


class WorkspaceKind(StrEnum):
    PERSONAL = "personal"
    DEMO = "demo"


class Role(StrEnum):
    OWNER = "owner"
    GUEST = "guest"


@dataclass(frozen=True, slots=True)
class SessionToken:
    """The secret a client presents: in the session cookie or a Bearer header."""

    value: str = field(repr=False)

    def __repr__(self) -> str:
        return "SessionToken(***)"


@dataclass(frozen=True, slots=True)
class SessionTokenHash:
    """What the database stores instead of the token (ADR 0008)."""

    value: str
