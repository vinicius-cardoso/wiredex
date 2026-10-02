"""Who is changing the workspace, and why, for the history the database records (17-history,
decision 4).

A write's transaction names its user and its reason next to its workspace, and the trigger
behind every tracked table reads them back. Neither travels as a parameter through the modules:
the composition root sets the actor once per request, right after it has authenticated the
caller, and anything that names a reason (a restore) wraps its call in `changing_for`. Both live
in context variables, so each request's task sees its own, and a job run from the command line
sees none and reads as Wiredex.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Actor:
    """The signed-in user a change is recorded for, by the name they have when they make it."""

    id: UUID
    name: str


_actor: ContextVar[Actor | None] = ContextVar("wiredex_actor", default=None)
_reason: ContextVar[str | None] = ContextVar("wiredex_change_reason", default=None)


def act_as(actor: Actor) -> None:
    """Every transaction from here to the end of the current task is this user's. Set by the
    composition root once a request is authenticated; a request's task ends with its response,
    so the next request starts with no actor."""
    _actor.set(actor)


def acting() -> Actor | None:
    """The user the current task acts for, or None for Wiredex itself."""
    return _actor.get()


@contextmanager
def changing_for(reason: str) -> Iterator[None]:
    """Every transaction opened inside the block names REASON, as a restore names `restore`."""
    token = _reason.set(reason)
    try:
        yield
    finally:
        _reason.reset(token)


def reason() -> str | None:
    """The reason the current block names, or None."""
    return _reason.get()
