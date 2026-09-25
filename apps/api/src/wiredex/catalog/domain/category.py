"""The tree parts hang from. A category knows its own name and its parent, nothing more.

Reading the tree is the application's job, so the rules that need to look around — is this
parent a descendant of mine, how deep would that put me — take what they need as arguments.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from wiredex.catalog.domain.errors import CategoryTooDeepError, CircularCategoryError
from wiredex.catalog.domain.values import CategoryId, CategoryName, WorkspaceId

# A root sits at level 1. Six is deep enough for Passives → Resistors → Thick film and
# shallow enough that the recursive ancestor read stays one cheap query.
MAX_CATEGORY_DEPTH = 6


def check_depth(ancestors: Sequence[CategoryId], below: int = 0) -> None:
    """Refuses a position past the cap (requirements 1.4 and 1.6).

    `ancestors` is the chain a category would sit under and `below` the levels of descendants
    riding along with it, which is how a move is checked for a whole subtree.

    A function, not a method: creating a category asks the question before there is a
    category to ask it of.
    """
    depth = len(ancestors) + 1 + below
    if depth > MAX_CATEGORY_DEPTH:
        raise CategoryTooDeepError(
            f"a category can't sit deeper than {MAX_CATEGORY_DEPTH} levels, "
            f"and this one would reach {depth}"
        )


@dataclass(eq=False)
class Category:
    """One node of the tree: a name among its siblings, and the schema its parts inherit."""

    id: CategoryId
    workspace_id: WorkspaceId
    parent_id: CategoryId | None
    name: CategoryName
    created_at: datetime

    def rename(self, name: CategoryName) -> bool:
        """Returns whether the name changed, so renaming to the current name commits
        nothing (requirement 1.8). Case counts: *Passives* and *passives* are two names."""
        if self.name == name:
            return False
        self.name = name
        return True

    def move_under(self, parent: Category | None, ancestors: Sequence[CategoryId]) -> None:
        """Re-parents the category, or puts it at the root when `parent` is None.

        `ancestors` is the candidate parent's own chain: the domain can't query, so the use
        case reads it and passes it in. Finding this category in it means the parent is one
        of its own descendants, which would cut the subtree loose from the root.
        """
        if parent is None:
            self.parent_id = None
            return
        if parent.id == self.id or self.id in ancestors:
            raise CircularCategoryError(
                f"{self.name} can't sit under itself or under one of its own descendants"
            )
        check_depth([*ancestors, parent.id])
        self.parent_id = parent.id
