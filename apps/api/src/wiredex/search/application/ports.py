"""What the search asks of the modules whose records it finds: one source per kind (19-command-
palette, decision 5).

The search imports no module. Each source is built in `bootstrap/search.py` over its module's own
`Find…` use case, which decides what matches and in what order; the search only asks, cuts and
groups. A source runs its module's unit of work and closes it before it answers, so the search
never holds two at once.
"""

from collections.abc import Sequence
from typing import Protocol

from wiredex.search.domain.search import SearchHit, SearchKind
from wiredex.search.domain.values import WorkspaceId


class SearchSource(Protocol):
    """One kind's share of a search, answered by the module that owns the kind."""

    @property
    def kind(self) -> SearchKind:
        """The kind of record this source finds, and so the group its hits go in."""
        ...

    async def find(self, workspace_id: WorkspaceId, text: str, limit: int) -> Sequence[SearchHit]:
        """The kind's records matching the text, in its module's order, at most `limit`, in a
        fixed number of statements whatever their number (requirement 6.1)."""
        ...
