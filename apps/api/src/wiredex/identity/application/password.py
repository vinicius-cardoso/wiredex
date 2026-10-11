"""Change your own password (23-change-password).

The rules, each there for a reason:

- **The current password is asked again.** A session alone doesn't change it, so a stolen
  cookie or an unlocked laptop can't lock the owner out or keep the account.
- **Wrong guesses are counted per user**, as failed logins are, and the count is checked
  before the password is: a stolen session gets five tries in fifteen minutes.
- **The new password has to differ** from the current one and not be the email or the name.
- **Every other session ends.** Whoever was logged in with the old password, on any device,
  is logged out; the session that made the change stays.
"""

from dataclasses import dataclass

from wiredex.identity.application.ports import LoginThrottle, PasswordHasher
from wiredex.identity.application.sessions import CurrentUser, UnitOfWorkFactory
from wiredex.identity.domain.errors import (
    SamePasswordError,
    TooManyAttemptsError,
    WeakPasswordError,
    WrongPasswordError,
)
from wiredex.identity.domain.values import MIN_PASSWORD_LENGTH, Password, PasswordHash
from wiredex.shared_kernel.application.ports import Clock


@dataclass(frozen=True, slots=True)
class PasswordChanged:
    """How many other sessions the change ended, for the page to say."""

    revoked_sessions: int


class ChangePassword:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        hasher: PasswordHasher,
        throttle: LoginThrottle,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._hasher = hasher
        self._throttle = throttle

    async def __call__(
        self, current: CurrentUser, current_password: str, new_password: str
    ) -> PasswordChanged:
        """The passwords arrive as typed: what is wrong with each is said in this order, so
        nothing about the new one is answered to someone who doesn't know the current one."""
        now = self._clock.now()
        key = f"password:{current.user.id}"
        if self._throttle.is_blocked([key], now):
            raise TooManyAttemptsError
        async with self._unit_of_work() as work:
            # Read again inside this unit of work: the one on CURRENT belongs to another.
            user = await work.users.get(current.user.id)
            if user is None or not self._knows(current_password, user.password_hash):
                self._throttle.record_failure([key], now)
                raise WrongPasswordError
            password = Password(new_password)
            if new_password == current_password:
                raise SamePasswordError
            user.ensure_unlike_account(password)
            user.change_password(self._hasher.hash(password))
            others = [
                session
                for session in await work.sessions.of_user(user.id)
                if session.id != current.session.id
            ]
            for session in others:
                await work.sessions.remove(session)
            await work.commit()
        self._throttle.clear(key)
        return PasswordChanged(len(others))

    def _knows(self, typed: str, stored: PasswordHash) -> bool:
        """Whether TYPED is the stored password. One too short or too long to be any
        password still costs a real check, so its answer takes as long as a wrong one's."""
        try:
            return self._hasher.verify(Password(typed), stored)
        except WeakPasswordError:
            self._hasher.verify(Password("x" * MIN_PASSWORD_LENGTH), None)
            return False
