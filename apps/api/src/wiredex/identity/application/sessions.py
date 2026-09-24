"""Log in, recognise a logged-in client, and log out (ADR 0008)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from wiredex.identity.application.ports import (
    IdentityUnitOfWork,
    LoginThrottle,
    PasswordHasher,
    SessionTokens,
)
from wiredex.identity.domain.errors import InvalidCredentialsError, TooManyAttemptsError
from wiredex.identity.domain.model import User
from wiredex.identity.domain.session import Session
from wiredex.identity.domain.values import Email, Password, SessionId, SessionToken
from wiredex.shared_kernel.application.ports import Clock, IdGenerator

type UnitOfWorkFactory = Callable[[], IdentityUnitOfWork]


@dataclass(frozen=True, slots=True)
class LoginAttempt:
    email: Email
    password: Password
    device: str
    ip: str

    def throttle_keys(self) -> tuple[str, str]:
        return f"account:{self.email}", f"ip:{self.ip}"


@dataclass(frozen=True, slots=True)
class LoggedIn:
    token: SessionToken
    user: User
    session: Session


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user: User
    session: Session


@dataclass(frozen=True, slots=True)
class LoginServices:
    clock: Clock
    ids: IdGenerator
    hasher: PasswordHasher
    tokens: SessionTokens
    throttle: LoginThrottle


class LogIn:
    def __init__(self, unit_of_work: UnitOfWorkFactory, services: LoginServices) -> None:
        self._unit_of_work = unit_of_work
        self._services = services

    async def __call__(self, attempt: LoginAttempt) -> LoggedIn:
        now = self._services.clock.now()
        keys = attempt.throttle_keys()
        if self._services.throttle.is_blocked(keys, now):
            raise TooManyAttemptsError
        async with self._unit_of_work() as work:
            user = await work.users.with_email(attempt.email)
            if user is None or not self._accepts(user, attempt.password, now):
                self._services.throttle.record_failure(keys, now)
                raise InvalidCredentialsError
            logged_in = self._start_session(user, attempt.device)
            await work.sessions.add(logged_in.session)
            await work.commit()
        self._services.throttle.clear(keys[0])
        return logged_in

    def _accepts(self, user: User | None, password: Password, now: datetime) -> bool:
        stored = None if user is None else user.password_hash
        matches = self._services.hasher.verify(password, stored)
        return matches and user is not None and user.is_active(now)

    def _start_session(self, user: User, device: str) -> LoggedIn:
        token = self._services.tokens.issue()
        session = Session.start(
            SessionId(self._services.ids.new_id()),
            user.id,
            self._services.tokens.hash(token),
            device,
            self._services.clock.now(),
        )
        return LoggedIn(token, user, session)


class Authenticate:
    """Turns a presented token into the current user, or None. Renews the session."""

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, clock: Clock, tokens: SessionTokens
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._tokens = tokens

    async def __call__(self, token: SessionToken) -> CurrentUser | None:
        now = self._clock.now()
        async with self._unit_of_work() as work:
            session = await work.sessions.with_token_hash(self._tokens.hash(token))
            if session is None:
                return None
            user = await work.users.get(session.user_id)
            if user is None or not (session.is_valid(now) and user.is_active(now)):
                await work.sessions.remove(session)
                await work.commit()
                return None
            if session.touch(now):
                await work.commit()
            return CurrentUser(user, session)


class LogOut:
    def __init__(self, unit_of_work: UnitOfWorkFactory, tokens: SessionTokens) -> None:
        self._unit_of_work = unit_of_work
        self._tokens = tokens

    async def __call__(self, token: SessionToken) -> None:
        async with self._unit_of_work() as work:
            session = await work.sessions.with_token_hash(self._tokens.hash(token))
            if session is not None:
                await work.sessions.remove(session)
                await work.commit()
