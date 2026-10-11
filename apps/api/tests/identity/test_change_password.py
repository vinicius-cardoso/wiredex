from datetime import timedelta

import pytest

from support.identity import EMAIL, World
from wiredex.identity.application.sessions import CurrentUser, LoggedIn, LoginAttempt
from wiredex.identity.domain.errors import (
    InvalidCredentialsError,
    PasswordLikeAccountError,
    SamePasswordError,
    TooManyAttemptsError,
    WeakPasswordError,
    WrongPasswordError,
)
from wiredex.identity.domain.values import Password

pytestmark = pytest.mark.anyio

OLD = "correct horse battery"
NEW = "a brand new passphrase"


async def log_in(world: World, password: str = OLD, device: str = "Firefox on Linux") -> LoggedIn:
    return await world.log_in(LoginAttempt(EMAIL, Password(password), device, "203.0.113.7"))


async def current(world: World, logged_in: LoggedIn) -> CurrentUser:
    found = await world.authenticate(logged_in.token)
    assert found is not None
    return found


async def test_the_new_password_logs_in_and_the_old_one_doesnt() -> None:
    world = await World().with_owner()
    me = await current(world, await log_in(world))

    await world.change_password(me, OLD, NEW)

    assert (await log_in(world, NEW)).user.email == EMAIL
    with pytest.raises(InvalidCredentialsError):
        await log_in(world, OLD)


async def test_every_other_session_ends_and_this_one_stays() -> None:
    world = await World().with_owner()
    laptop = await log_in(world, device="Laptop")
    phone = await log_in(world, device="Phone")
    tablet = await log_in(world, device="Tablet")

    changed = await world.change_password(await current(world, laptop), OLD, NEW)

    assert changed.revoked_sessions == 2
    assert await world.authenticate(laptop.token) is not None
    assert await world.authenticate(phone.token) is None
    assert await world.authenticate(tablet.token) is None


async def test_a_wrong_current_password_changes_nothing() -> None:
    world = await World().with_owner()
    laptop = await log_in(world)
    phone = await log_in(world, device="Phone")
    commits = world.identity.commits

    with pytest.raises(WrongPasswordError):
        await world.change_password(await current(world, laptop), "not the password", NEW)

    assert world.identity.commits == commits
    assert await world.authenticate(phone.token) is not None
    assert (await log_in(world, OLD)).user.email == EMAIL


@pytest.mark.parametrize("typed", ["", "short", "x" * 2000])
async def test_a_current_password_no_password_could_be_is_just_wrong(typed: str) -> None:
    world = await World().with_owner()

    with pytest.raises(WrongPasswordError):
        await world.change_password(await current(world, await log_in(world)), typed, NEW)


async def test_the_fifth_wrong_guess_locks_the_change_even_for_the_right_password() -> None:
    world = await World().with_owner()
    me = await current(world, await log_in(world))
    for _ in range(5):
        with pytest.raises(WrongPasswordError):
            await world.change_password(me, "not the password", NEW)

    with pytest.raises(TooManyAttemptsError):
        await world.change_password(me, OLD, NEW)

    # The window passes, and the right password works again.
    world.clock.advance(timedelta(minutes=15))
    assert (await world.change_password(me, OLD, NEW)).revoked_sessions == 0


async def test_wrong_guesses_at_the_change_dont_lock_logging_in() -> None:
    world = await World().with_owner()
    me = await current(world, await log_in(world))
    for _ in range(5):
        with pytest.raises(WrongPasswordError):
            await world.change_password(me, "not the password", NEW)

    assert (await log_in(world)).user.email == EMAIL


async def test_a_change_that_works_forgets_the_wrong_guesses_before_it() -> None:
    world = await World().with_owner()
    me = await current(world, await log_in(world))
    for _ in range(4):
        with pytest.raises(WrongPasswordError):
            await world.change_password(me, "not the password", NEW)
    await world.change_password(me, OLD, NEW)

    for _ in range(4):
        with pytest.raises(WrongPasswordError):
            await world.change_password(me, "not the password", OLD)
    await world.change_password(me, NEW, "yet another passphrase")


@pytest.mark.parametrize(
    ("new", "error"),
    [
        ("too short", WeakPasswordError),
        ("x" * 1025, WeakPasswordError),
        (OLD, SamePasswordError),
        ("owner@example.com", PasswordLikeAccountError),
        ("MyOwner@Example.com!", PasswordLikeAccountError),
        ("the OWNER of the bench", PasswordLikeAccountError),
    ],
)
async def test_a_new_password_that_wont_do_is_refused_and_nothing_changes(
    new: str, error: type[Exception]
) -> None:
    world = await World().with_owner()
    phone = await log_in(world, device="Phone")
    me = await current(world, await log_in(world))
    commits = world.identity.commits

    with pytest.raises(error):
        await world.change_password(me, OLD, new)

    assert world.identity.commits == commits
    assert await world.authenticate(phone.token) is not None
    assert (await log_in(world, OLD)).user.email == EMAIL


async def test_what_is_wrong_with_the_new_password_isnt_said_before_the_current_one_is_right() -> (
    None
):
    world = await World().with_owner()

    with pytest.raises(WrongPasswordError):
        await world.change_password(
            await current(world, await log_in(world)), "not the password", "short"
        )


async def test_the_password_is_never_in_what_a_refusal_says() -> None:
    world = await World().with_owner()
    me = await current(world, await log_in(world))

    for current_password, new in [("hunter2 hunter2", NEW), (OLD, "owner@example.com")]:
        with pytest.raises(ValueError) as refused:  # noqa: PT011  any identity refusal
            await world.change_password(me, current_password, new)
        assert current_password not in str(refused.value)
        assert new not in str(refused.value)
