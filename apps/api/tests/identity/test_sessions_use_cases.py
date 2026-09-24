from datetime import timedelta

import pytest

from support.identity import EMAIL, NOW, World
from wiredex.identity.application.sessions import (
    LoginAttempt,
)
from wiredex.identity.domain.errors import InvalidCredentialsError, TooManyAttemptsError
from wiredex.identity.domain.values import Email, Password, SessionToken

pytestmark = pytest.mark.anyio


def attempt(password: str = "correct horse battery", email: Email = EMAIL) -> LoginAttempt:
    return LoginAttempt(email, Password(password), "Firefox on Linux", "203.0.113.7")


async def test_logging_in_starts_a_session_the_token_opens() -> None:
    world = await World().with_owner()

    logged_in = await world.log_in(attempt())
    current = await world.authenticate(logged_in.token)

    assert current is not None
    assert current.user.email == EMAIL
    assert current.session.device == "Firefox on Linux"
    # Only the token's hash is stored.
    assert logged_in.token.value not in {h.value for h in world.identity.sessions.saved}


async def test_a_wrong_password_and_an_unknown_email_fail_the_same_way() -> None:
    world = await World().with_owner()

    with pytest.raises(InvalidCredentialsError) as wrong_password:
        await world.log_in(attempt("wrong password here"))
    with pytest.raises(InvalidCredentialsError) as unknown_email:
        await world.log_in(attempt(email=Email("nobody@example.com")))

    assert str(wrong_password.value) == str(unknown_email.value) == "wrong email or password"


async def test_an_expired_guest_cannot_log_in() -> None:
    world = await World().with_owner()
    next(iter(world.identity.users.saved.values())).expires_at = NOW

    with pytest.raises(InvalidCredentialsError):
        await world.log_in(attempt())


async def test_repeated_failures_lock_the_account_even_for_the_right_password() -> None:
    world = await World().with_owner()
    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            await world.log_in(attempt("wrong password here"))

    with pytest.raises(TooManyAttemptsError):
        await world.log_in(attempt())


async def test_a_successful_login_resets_the_account_counter() -> None:
    world = await World().with_owner()
    for _ in range(4):
        with pytest.raises(InvalidCredentialsError):
            await world.log_in(attempt("wrong password here"))

    await world.log_in(attempt())

    with pytest.raises(InvalidCredentialsError):  # counting from zero again, not locked
        await world.log_in(attempt("wrong password here"))


async def test_an_unknown_or_expired_token_is_nobody() -> None:
    world = await World().with_owner()
    token = (await world.log_in(attempt())).token

    assert await world.authenticate(SessionToken("made-up")) is None
    world.clock.advance(timedelta(days=31))
    assert await world.authenticate(token) is None
    assert world.identity.sessions.saved == {}  # the dead session was removed


async def test_logging_out_ends_the_session() -> None:
    world = await World().with_owner()
    token = (await world.log_in(attempt())).token

    await world.log_out(token)
    await world.log_out(token)  # logging out twice is harmless

    assert await world.authenticate(token) is None
