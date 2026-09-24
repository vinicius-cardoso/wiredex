from argon2 import PasswordHasher as Argon2
from argon2.exceptions import InvalidHashError, VerificationError

from wiredex.identity.domain.values import Password, PasswordHash


class Argon2PasswordHasher:
    """Argon2id with RFC 9106's low-memory profile (64 MiB, 3 passes, 4 lanes).

    That is argon2-cffi's default. It fits the 1 GB host because logins are rare and
    rate-limited, so a few of these never run at once.
    """

    def __init__(self) -> None:
        self._argon2 = Argon2()

    def hash(self, password: Password) -> PasswordHash:
        return PasswordHash(self._argon2.hash(password.value))

    def verify(self, password: Password, password_hash: PasswordHash) -> bool:
        try:
            return self._argon2.verify(password_hash.value, password.value)
        except VerificationError, InvalidHashError:
            return False
