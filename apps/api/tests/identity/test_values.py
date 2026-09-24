import pytest

from wiredex.identity.domain.errors import InvalidEmailError, InvalidNameError
from wiredex.identity.domain.values import Email, Name, PasswordHash


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
