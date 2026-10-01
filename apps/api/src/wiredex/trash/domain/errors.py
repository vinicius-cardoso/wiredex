"""What the trash refuses."""


class TrashError(ValueError):
    """A request the trash can't answer. The message is safe to show to users."""


class TrashItemNotFoundError(TrashError):
    """A record that isn't in the trash: never moved there, already restored or deleted for good,
    or another workspace's. A 404, so an id says nothing about another bench (requirement 5.3)."""


class InvalidTrashCursorError(TrashError):
    """A cursor the API didn't give (requirement 4.4). A client never builds one, it only echoes
    the last page's, so every way of being malformed is this one refusal."""
