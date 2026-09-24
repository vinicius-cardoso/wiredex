import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import NewType
from uuid import UUID

from wiredex.identity.domain.errors import InvalidEmailError, InvalidNameError, WeakPasswordError

UserId = NewType("UserId", UUID)
WorkspaceId = NewType("WorkspaceId", UUID)

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
