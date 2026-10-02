"""The search's use case: the workspace searched across every source, one after the other.

The sources are asked in turn, never at once: each opens its module's unit of work and closes it
before the next one opens, so a request holds one pooled connection at a time (19-command-
palette, decision 4).
"""

from collections.abc import Sequence

from wiredex.search.application.ports import SearchSource
from wiredex.search.domain.search import SearchResults, SearchText, group, results
from wiredex.search.domain.values import WorkspaceId


class SearchWorkspace:
    """Every kind's records matching a text, a group per kind (requirements 1.1 to 1.4).

    Each source is asked for one more hit than a group shows, so the group can say whether more
    match (decision 3). The limit is the route's, 1 to 20.
    """

    def __init__(self, sources: Sequence[SearchSource]) -> None:
        self._sources = tuple(sources)

    async def __call__(
        self, workspace_id: WorkspaceId, text: SearchText, limit: int
    ) -> SearchResults:
        groups = [
            group(source.kind, await source.find(workspace_id, text.value, limit + 1), limit)
            for source in self._sources
        ]
        return results(text, groups)
