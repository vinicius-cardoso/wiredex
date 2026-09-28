"""The tree parts hang from. A category knows its own name and its parent, nothing more.

Reading the tree is the application's job, so the rules that need to look around — is this
parent a descendant of mine, how deep would that put me — take what they need as arguments.
`CategoryPaths` is the one that takes the whole tree, because naming a category by its path
means knowing every other path that ends the same way.
"""

import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from wiredex.catalog.domain.errors import (
    AmbiguousCategoryError,
    CategoryNotFoundError,
    CategoryTooDeepError,
    CircularCategoryError,
)
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
    # Whether the parts here are tracked as individual units (inventory reads this through a
    # port). `None` inherits the nearest ancestor's answer; an explicit value overrides it,
    # and nothing set anywhere in the chain means lot-counted (requirements 6.1, 6.2).
    tracked_individually: bool | None = None
    # Whether the parts here are consumables: never received, reserved or counted short.
    # `None` inherits the nearest ancestor's answer, as tracking does, and the two flags
    # resolve independently of each other (09's decisions 2 and 3).
    not_stocked: bool | None = None

    def rename(self, name: CategoryName) -> bool:
        """Returns whether the name changed, so renaming to the current name commits
        nothing (requirement 1.8). Case counts: *Passives* and *passives* are two names."""
        if self.name == name:
            return False
        self.name = name
        return True

    def set_tracking(self, tracked: bool | None) -> bool:
        """Sets or clears the flag, and answers whether it changed, so a no-op commits nothing.

        `None` clears it back to inheriting the parent; `True`/`False` overrides (design's
        catalog change). Only future receives are affected — existing lots stay (6.4), which
        is the application's and inventory's concern, not this entity's."""
        if self.tracked_individually == tracked:
            return False
        self.tracked_individually = tracked
        return True

    def set_not_stocked(self, not_stocked: bool | None) -> bool:
        """Sets or clears the flag, and answers whether it changed, so a no-op commits nothing.

        As with tracking, only what happens next is affected: inventory refuses new stock for
        a consumable at receive time, and stock already held stays (09's requirement 1.6)."""
        if self.not_stocked == not_stocked:
            return False
        self.not_stocked = not_stocked
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


@dataclass(frozen=True, slots=True)
class CategoryFlags:
    """A category's resolved answers: each the nearest set value from it up to the root, and
    False when nothing in the chain sets it. The two resolve independently (09's decision 3):
    a board type can be tracked as units and still stop being stocked."""

    tracked_individually: bool = False
    not_stocked: bool = False


def resolve_flags_of(chain: Sequence[Category]) -> CategoryFlags:
    """Both flags of a category, given its chain from the root down to it.

    The nearest set value wins, so walking the chain from the category up to the root and
    taking the first explicit answer resolves each flag; nothing set anywhere is False,
    lot-counted and stocked (05's requirements 6.1, 6.2; 09's 1.2, 1.3). `chain` is root
    first, the category itself last, the order `Categories.ancestors` reads plus the category.
    """
    tracked: bool | None = None
    not_stocked: bool | None = None
    for node in reversed(chain):
        if tracked is None:
            tracked = node.tracked_individually
        if not_stocked is None:
            not_stocked = node.not_stocked
    return CategoryFlags(tracked_individually=tracked is True, not_stocked=not_stocked is True)


def flags_in_tree(category: Category, by_id: Mapping[CategoryId, Category]) -> CategoryFlags:
    """The same answer from a tree already in memory, walking the parent links.

    What the category list, the drafts and `DescribeParts` use instead of a chain query per
    category. A missing parent id (another workspace's row can't be here) ends the walk at
    the root, as `CategoryPaths` reads it.
    """
    chain: list[Category] = []
    current: Category | None = category
    while current is not None:
        chain.append(current)
        current = None if current.parent_id is None else by_id.get(current.parent_id)
    chain.reverse()
    return resolve_flags_of(chain)


_SEPARATOR = "/"
# What `path_of` prints between names: spaced, so a path reads as a breadcrumb.
_SHOWN_SEPARATOR = f" {_SEPARATOR} "

# A name as `find` compares it: its folded pieces between separators.
type _Tokens = tuple[str, ...]


class CategoryPaths:
    """The tree read once, answering which category a typed path names (design decision 8).

    A path is names separated by `/`, root first: `Passives / Resistors`. It names the
    category whose whole chain from the root is those names, or else every category whose
    chain ends with them, so `Resistors` alone is enough while only one category has that
    name. Names are compared folded: compatibility forms unified, accents dropped, case
    folded, whitespace collapsed, which is how a sheet typed on another keyboard still finds
    `Resistências`.

    A name may hold a `/` itself (`I/O expanders`). Its pieces are compared as the typed
    pieces are, and a match has to start where a name starts, so `I/O expanders` finds it
    and `O expanders` doesn't.
    """

    __slots__ = ("_by_id", "_by_last_token", "_chains")

    def __init__(self, categories: Iterable[Category]) -> None:
        self._by_id = {category.id: category for category in categories}
        self._chains = {category.id: self._chain(category) for category in self._by_id.values()}
        self._by_last_token: dict[str, list[Category]] = defaultdict(list)
        for category in self._by_id.values():
            # A match ends on the category's own name, so only categories whose name ends
            # with the typed last piece are candidates: `find` never scans the whole tree.
            self._by_last_token[_tokens(category.name.value)[-1]].append(category)

    def find(self, text: str) -> Category:
        """The one category the path names, or a refusal saying why there isn't one.

        A category whose whole path is the typed names wins over those whose path they only
        end: otherwise a root `Boards` beside `Legacy / Boards` could never be named, and
        the path the preview prints for it wouldn't read back.
        """
        typed = _tokens(text)
        whole: list[Category] = []
        tail: list[Category] = []
        for category in self._by_last_token.get(typed[-1], ()):
            chain = self._chains[category.id]
            levels = _levels_matched(chain, typed)
            if levels is not None:
                (whole if levels == len(chain) else tail).append(category)
        matches = whole or tail
        if not matches:
            raise CategoryNotFoundError(f"no category's path ends with {_shown(text)!r}")
        if len(matches) > 1:
            paths = sorted(self.path_of(category) for category in matches)
            raise AmbiguousCategoryError(
                f"{_shown(text)!r} could be {' or '.join(paths)}: type more of its path"
            )
        return matches[0]

    def path_of(self, category: Category) -> str:
        """The names from the root down to the category, as the preview shows them."""
        return _SHOWN_SEPARATOR.join(str(node.name) for node in self._chain(category))

    def _chain(self, category: Category) -> list[Category]:
        """Root first, the category last. A parent missing from the tree ends the walk, as
        `ListCategories` reads it: another workspace's row can't be here."""
        chain: list[Category] = []
        current: Category | None = category
        while current is not None:
            chain.append(current)
            current = None if current.parent_id is None else self._by_id.get(current.parent_id)
        chain.reverse()
        return chain


def _levels_matched(chain: Sequence[Category], typed: _Tokens) -> int | None:
    """How many names, from the category up, the typed pieces are; None when the chain
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
    return tuple(_fold(piece) for piece in text.split(_SEPARATOR))


def _fold(text: str) -> str:
    """A name as `find` compares it. NFKC first, so a full-width letter or a ligature reads
    as its plain letters; then NFKD after case folding, whose combining marks are the accents
    dropped (casefold itself can leave one, as İ becomes i with a dot above)."""
    folded = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text).casefold())
    bare = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(bare.split())


def _shown(text: str) -> str:
    """The typed path in a refusal: its names trimmed and spaced as `path_of` spaces them."""
    return _SHOWN_SEPARATOR.join(" ".join(piece.split()) for piece in text.split(_SEPARATOR))
