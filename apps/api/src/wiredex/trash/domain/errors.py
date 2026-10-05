"""What the trash refuses."""


class TrashError(ValueError):
    """A request the trash can't answer. The message is safe to show to users."""


class TrashItemNotFoundError(TrashError):
    """A record that isn't in the trash: never moved there, already restored or deleted for good,
    or another workspace's. A 404, so an id says nothing about another bench (requirement 5.3)."""


class InvalidTrashFilterError(TrashError):
    """A text to narrow the trash by that is longer than the box it is typed in."""
