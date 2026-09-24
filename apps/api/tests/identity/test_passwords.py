from wiredex.identity.domain.values import Password, PasswordHash
from wiredex.identity.infrastructure.passwords import Argon2PasswordHasher

PASSWORD = Password("correct horse battery staple")


def test_hashes_are_argon2id_and_salted() -> None:
    hasher = Argon2PasswordHasher()

    first, second = hasher.hash(PASSWORD), hasher.hash(PASSWORD)

    assert first.value.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert first != second  # a fresh salt every time


def test_only_the_right_password_verifies() -> None:
    hasher = Argon2PasswordHasher()
    stored = hasher.hash(PASSWORD)

    assert hasher.verify(PASSWORD, stored)
    assert not hasher.verify(Password("correct horse battery stapler"), stored)


def test_a_corrupt_hash_never_verifies() -> None:
    assert not Argon2PasswordHasher().verify(PASSWORD, PasswordHash("not-a-hash"))
