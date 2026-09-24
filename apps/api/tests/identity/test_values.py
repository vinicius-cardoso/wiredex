from datetime import timedelta

import pytest

from wiredex.identity.domain.errors import (
    InvalidEmailError,
    InvalidLifetimeError,
    InvalidNameError,
    WeakPasswordError,
)
from wiredex.identity.domain.values import Email, GuestLifetime, Name, Password, PasswordHash


def test_emails_are_trimmed_and_lower_cased() -> None:
    assert Email("  Vinicius@Example.COM ").value == "vinicius@example.com"
    assert Email("A@b.co") == Email("a@B.CO")


@pytest.mark.parametrize(
    "text", ["", "no-at-sign", "two@@signs.com", "a@nodot", "a b@c.d", "x@" + "y" * 250 + ".com"]
)
def test_invalid_emails_are_rejected(text: str) -> None:
    with pytest.raises(InvalidEmailError):
        Email(text)


def test_names_collapse_whitespace() -> None:
    assert Name("  My   Bench ").value == "My Bench"


@pytest.mark.parametrize("text", ["", "   ", "x" * 81])
def test_names_need_1_to_80_characters(text: str) -> None:
    with pytest.raises(InvalidNameError):
        Name(text)


def test_password_hashes_never_show_in_repr() -> None:
    assert "argon2" not in repr(PasswordHash("$argon2id$v=19$secret"))


@pytest.mark.parametrize("text", ["short", "x" * 11, "x" * 1025])
def test_passwords_need_12_to_1024_characters(text: str) -> None:
    with pytest.raises(WeakPasswordError):
        Password(text)


def test_passwords_never_show_in_repr() -> None:
    assert "horse" not in repr(Password("correct horse battery staple"))


@pytest.mark.parametrize(
    ("text", "lifetime"),
    [("12h", timedelta(hours=12)), (" 7D ", timedelta(days=7)), ("2w", timedelta(weeks=2))],
)
def test_guest_lifetimes_read_hours_days_and_weeks(text: str, lifetime: timedelta) -> None:
    assert GuestLifetime.parse(text).value == lifetime


@pytest.mark.parametrize("text", ["7", "d7", "7 days", "1.5d", ""])
def test_guest_lifetimes_need_a_number_and_a_unit(text: str) -> None:
    with pytest.raises(InvalidLifetimeError, match="like 12h, 7d or 2w"):
        GuestLifetime.parse(text)


@pytest.mark.parametrize("text", ["0h", "91d", "13w"])
def test_guest_lifetimes_last_from_an_hour_to_90_days(text: str) -> None:
    with pytest.raises(InvalidLifetimeError, match="from 1 hour to 90 days"):
        GuestLifetime.parse(text)
