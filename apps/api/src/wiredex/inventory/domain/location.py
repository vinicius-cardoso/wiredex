"""A node of the storage tree: room → cabinet → drawer → bin. A location knows its own name,
its short code and its parent, nothing more.

Reading the tree is the application's job, so the rules that need to look around — is this
parent a descendant of mine, how deep would that put me — take what they need as arguments,
exactly as ``Category`` does.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from wiredex.inventory.domain.errors import CircularLocationError, InventoryError
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
