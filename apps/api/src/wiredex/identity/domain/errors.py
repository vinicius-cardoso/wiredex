class IdentityError(ValueError):
    """A value that breaks an identity rule. The message is safe to show to users."""


class InvalidEmailError(IdentityError):
    pass


class InvalidNameError(IdentityError):
    pass


class WeakPasswordError(IdentityError):
    pass


class EmailAlreadyUsedError(IdentityError):
    pass


class InvalidLifetimeError(IdentityError):
    pass


class InvalidCredentialsError(IdentityError):
    """Deliberately vague: never reveals whether the email or the password was wrong."""

    def __init__(self) -> None:
        super().__init__("wrong email or password")


class SessionNotFoundError(IdentityError):
    """Also raised for someone else's session: its existence is none of your business."""

    def __init__(self) -> None:
        super().__init__("no such session")


class TooManyAttemptsError(IdentityError):
    def __init__(self) -> None:
        super().__init__("too many failed attempts; try again in a few minutes")


class GuestsCannotInviteError(IdentityError):
    """A guest asked to invite someone: only an account that doesn't expire shares a demo."""

    def __init__(self) -> None:
        super().__init__("a guest account can't invite anyone")


class AccountNotFoundError(IdentityError):
    """No account uses that email."""


class WrongPasswordError(IdentityError):
    """The current password given to change it isn't the account's."""

    def __init__(self) -> None:
        super().__init__("that isn't your current password")


class SamePasswordError(IdentityError):
    """The new password is the current one: nothing would change, and whoever knows the old
    one would still get in."""

    def __init__(self) -> None:
        super().__init__("the new password is the current one: choose a different one")


class PasswordLikeAccountError(IdentityError):
    """The new password is, or holds, the account's email or name: the first thing anyone
    guessing would try."""

    def __init__(self) -> None:
        super().__init__("a password can't be or contain your email or your name")
