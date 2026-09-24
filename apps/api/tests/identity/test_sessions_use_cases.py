from dataclasses import replace
from datetime import timedelta
from uuid import uuid7

import pytest

from support.identity import EMAIL, NOW, World
from wiredex.identity.application.sessions import (
    CurrentUser,
    LoginAttempt,
)
from wiredex.identity.domain.errors import (
    InvalidCredentialsError,
    SessionNotFoundError,
    TooManyAttemptsError,
)
from wiredex.identity.domain.values import (
    Email,
    Password,
    SessionId,
    SessionToken,
    SessionTokenHash,
    UserId,
)

pytestmark = pytest.mark.anyio


def attempt(
    password: str = "correct horse battery",
    email: Email = EMAIL,
    device: str = "Firefox on Linux",
) -> LoginAttempt:
    return LoginAttempt(email, Password(password), device, "203.0.113.7")


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


async def log_in_on(world: World, device: str) -> tuple[SessionToken, CurrentUser]:
    token = (await world.log_in(attempt(device=device))).token
    current = await world.authenticate(token)
    assert current is not None
    return token, current


async def test_your_sessions_list_the_most_recent_first_and_mark_the_current_one() -> None:
    world = await World().with_owner()
    await log_in_on(world, "Laptop")
    world.clock.advance(timedelta(hours=1))
    _, phone = await log_in_on(world, "Phone")

    sessions = await world.list_sessions(phone)

    assert [(s.session.device, s.is_current) for s in sessions] == [
        ("Phone", True),
        ("Laptop", False),
    ]


async def test_expired_sessions_are_not_listed() -> None:
    world = await World().with_owner()
    await log_in_on(world, "Old laptop")
    world.clock.advance(timedelta(days=31))
    _, phone = await log_in_on(world, "Phone")

    sessions = await world.list_sessions(phone)

    assert [s.session.device for s in sessions] == ["Phone"]


async def test_revoking_a_session_logs_only_that_device_out() -> None:
    world = await World().with_owner()
    laptop_token, laptop = await log_in_on(world, "Laptop")
    phone_token, phone = await log_in_on(world, "Phone")

    await world.revoke_session(phone, laptop.session.id)

    assert await world.authenticate(laptop_token) is None
    assert await world.authenticate(phone_token) is not None


async def test_only_your_own_sessions_can_be_revoked() -> None:
    world = await World().with_owner()
    _, phone = await log_in_on(world, "Phone")
    someone_elses = replace(
        phone.session,
        id=SessionId(uuid7()),
        user_id=UserId(uuid7()),
        token_hash=SessionTokenHash("someone else's"),
    )
    await world.identity.sessions.add(someone_elses)

    for session_id in (someone_elses.id, SessionId(uuid7())):
        with pytest.raises(SessionNotFoundError):
            await world.revoke_session(phone, session_id)
