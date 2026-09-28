"""A node of the storage tree: room → cabinet → drawer → bin. A location knows its own name,
its short code and its parent, nothing more.

Reading the tree is the application's job, so the rules that need to look around — is this
parent a descendant of mine, how deep would that put me — take what they need as arguments,
exactly as ``Category`` does. `LocationPaths` is the one that takes the whole tree, because
naming a location by its path means knowing every other path that ends the same way.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from wiredex.inventory.domain.errors import (
    AmbiguousLocationError,
    CircularLocationError,
    InvalidShortCodeError,
    InventoryError,
    LocationNotFoundError,
)
from wiredex.inventory.domain.folding import fold
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    ShortCode,
    WorkspaceId,
)

# A root sits at level 1. Six is deep enough for room → cabinet → drawer → bin with room to
# spare, and shallow enough that the recursive ancestor read stays one cheap query.
MAX_LOCATION_DEPTH = 6


class LocationTooDeepError(InventoryError):
    """A location, or one of its descendants, would sit past the depth cap."""


def check_depth(ancestors: Sequence[LocationId], below: int = 0) -> None:
    """Refuses a position past the cap (requirements 1.4 and 1.6).

    `ancestors` is the chain a location would sit under and `below` the levels of descendants
    riding along with it, which is how a move is checked for a whole subtree.

    A function, not a method: creating a location asks the question before there is a
    location to ask it of.
    """
    depth = len(ancestors) + 1 + below
    if depth > MAX_LOCATION_DEPTH:
        raise LocationTooDeepError(
            f"a location can't sit deeper than {MAX_LOCATION_DEPTH} levels, "
            f"and this one would reach {depth}"
        )


@dataclass(eq=False)
class Location:
    """One node of the tree: a name among its siblings, a short code assigned once."""

    id: LocationId
    workspace_id: WorkspaceId
    parent_id: LocationId | None
    code: ShortCode
    name: LocationName
    created_at: datetime

    def rename(self, name: LocationName) -> bool:
        """Returns whether the name changed, so renaming to the current name commits
        nothing (requirement 1.9). Case counts: *Lab* and *lab* are two names.

        The short code is assigned once at creation and untouched here (requirement 1.8).
        """
        if self.name == name:
            return False
        self.name = name
        return True

    def move_under(self, parent: Location | None, ancestors: Sequence[LocationId]) -> None:
        """Re-parents the location, or puts it at the root when `parent` is None.

        `ancestors` is the candidate parent's own chain: the domain can't query, so the use
        case reads it and passes it in. Finding this location in it means the parent is one
        of its own descendants, which would cut the subtree loose from the root (1.5).

        The short code is untouched by a move (requirement 1.8).
        """
        if parent is None:
            self.parent_id = None
            return
        if parent.id == self.id or self.id in ancestors:
            raise CircularLocationError(
                f"{self.name} can't sit under itself or under one of its own descendants"
            )
        check_depth([*ancestors, parent.id])
        self.parent_id = parent.id


_SEPARATOR = "/"
# What `path_of` prints between names: spaced, so a path reads as a breadcrumb.
_SHOWN_SEPARATOR = f" {_SEPARATOR} "

# A name as `find` compares it: its folded pieces between separators.
type _Tokens = tuple[str, ...]


class LocationPaths:
    """The tree read once, answering which location a typed short code or path names (design
    decision 8, requirement 6.5).

    A short code is tried first, in any case, since a code is unique and exact: that is what
    the codes on the drawers are for. Otherwise the text is a path, names separated by `/`
    root first, found the way catalog's `CategoryPaths` finds a category, restated here
    because inventory can't import catalog: the location whose whole chain from the root is
    those names, or else every location whose chain ends with them, so `Drawer 3` alone is
    enough while only one location has that name. Names are compared folded, so a sheet
    typed on another keyboard still finds `Gaveta três`.

    A name may hold a `/` itself (`In/out tray`). Its pieces are compared as the typed pieces
    are, and a match has to start where a name starts, so `In/out tray` finds it and
    `out tray` doesn't.
    """

    __slots__ = ("_by_code", "_by_id", "_by_last_token", "_chains")

    def __init__(self, locations: Iterable[Location]) -> None:
        self._by_id = {location.id: location for location in locations}
        self._by_code = {location.code.value: location for location in self._by_id.values()}
        self._chains = {location.id: self._chain(location) for location in self._by_id.values()}
        self._by_last_token: dict[str, list[Location]] = defaultdict(list)
        for location in self._by_id.values():
            # A match ends on the location's own name, so only locations whose name ends with
            # the typed last piece are candidates: `find` never scans the whole tree.
            self._by_last_token[_tokens(location.name.value)[-1]].append(location)

    def find(self, text: str) -> Location:
        """The one location the code or path names, or a refusal saying why there isn't one.

        Text that reads as a short code no location holds is still tried as a path, since a
        location's name is free text. A location whose whole path is the typed names wins
        over those whose path they only end, so a root `Bench` beside `Lab / Bench` can still
        be named, and the path the preview prints reads back.
        """
        coded = self._coded(text)
        return coded if coded is not None else self._on_path(text)

    def path_of(self, location: Location) -> str:
        """The names from the root down to the location, as the preview shows them."""
        return _SHOWN_SEPARATOR.join(str(node.name) for node in self._chain(location))

    def _coded(self, text: str) -> Location | None:
        try:
            code = ShortCode(text)
        except InvalidShortCodeError:
            return None
        return self._by_code.get(code.value)

    def _on_path(self, text: str) -> Location:
        typed = _tokens(text)
        whole: list[Location] = []
        tail: list[Location] = []
        for location in self._by_last_token.get(typed[-1], ()):
            chain = self._chains[location.id]
            levels = _levels_matched(chain, typed)
            if levels is not None:
                (whole if levels == len(chain) else tail).append(location)
        matches = whole or tail
        if not matches:
            raise LocationNotFoundError(
                f"{_shown(text)!r} is neither a location's short code nor the end of its path"
            )
        if len(matches) > 1:
            paths = sorted(self.path_of(location) for location in matches)
            raise AmbiguousLocationError(
                f"{_shown(text)!r} could be {' or '.join(paths)}: type more of its path, or "
                f"its short code"
            )
        return matches[0]

    def _chain(self, location: Location) -> list[Location]:
        """Root first, the location last. A parent missing from the tree ends the walk, as
        the locations page reads it: another workspace's row can't be here."""
        chain: list[Location] = []
        current: Location | None = location
        while current is not None:
            chain.append(current)
            current = None if current.parent_id is None else self._by_id.get(current.parent_id)
        chain.reverse()
        return chain


def _levels_matched(chain: Sequence[Location], typed: _Tokens) -> int | None:
    """How many names, from the location up, the typed pieces are; None when the chain
    doesn't end with them.

    Each name has to match all of its own pieces, so a typed path only ever starts where a
    name starts.
    """
    remaining = typed
    for levels, node in enumerate(reversed(chain), start=1):
        name = _tokens(node.name.value)
        if remaining[-len(name) :] != name:
            return None
        remaining = remaining[: -len(name)]
        if not remaining:
            return levels
    return None


def _tokens(text: str) -> _Tokens:
    return tuple(fold(piece) for piece in text.split(_SEPARATOR))


def _shown(text: str) -> str:
    """The typed text in a refusal: its names trimmed and spaced as `path_of` spaces them."""
    return _SHOWN_SEPARATOR.join(" ".join(piece.split()) for piece in text.split(_SEPARATOR))
