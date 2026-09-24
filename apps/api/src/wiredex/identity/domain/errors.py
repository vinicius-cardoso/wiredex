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


class InvalidCredentialsError(IdentityError):
    """Deliberately vague: never reveals whether the email or the password was wrong."""

    def __init__(self) -> None:
        super().__init__("wrong email or password")


class TooManyAttemptsError(IdentityError):
    def __init__(self) -> None:
        super().__init__("too many failed logins; try again in a few minutes")
