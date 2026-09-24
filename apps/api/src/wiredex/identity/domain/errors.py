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
