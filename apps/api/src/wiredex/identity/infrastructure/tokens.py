import hashlib
import secrets

from wiredex.identity.domain.values import SessionToken, SessionTokenHash


class SecretSessionTokens:
    """256-bit random tokens, stored as SHA-256.

    A fast hash is right here, unlike for passwords: the token is random, so there is
    nothing to guess, and it is checked on every request.
    """

    def issue(self) -> SessionToken:
        return SessionToken(secrets.token_urlsafe(32))

    def hash(self, token: SessionToken) -> SessionTokenHash:
        return SessionTokenHash(hashlib.sha256(token.value.encode()).hexdigest())
