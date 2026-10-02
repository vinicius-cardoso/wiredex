"""In-memory sources for the search, shared by its use-case and API tests.

Each source holds one kind's hits, already in its module's order, and answers the first
`limit` of those whose title holds the text, folded, as the modules' finds do. Every question
is recorded in a log the sources share, so a test sees which were asked, in what order and for
how many.
"""

from dataclasses import dataclass, field
from uuid import uuid7

from wiredex.search.domain.search import SearchHit, SearchKind
from wiredex.search.domain.values import WorkspaceId

BENCH = WorkspaceId(uuid7())


@dataclass(frozen=True, slots=True)
class Asked:
    kind: SearchKind
    workspace_id: WorkspaceId
    text: str
    limit: int


@dataclass
class FakeSource:
    kind: SearchKind
    hits: list[SearchHit] = field(default_factory=list)
    log: list[Asked] = field(default_factory=list)

    async def find(self, workspace_id: WorkspaceId, text: str, limit: int) -> list[SearchHit]:
        self.log.append(Asked(self.kind, workspace_id, text, limit))
        wanted = text.lower()
        return [hit for hit in self.hits if wanted in hit.title.lower()][:limit]

    def hold(self, *titles: str, detail: str | None = None) -> list[SearchHit]:
        held = [SearchHit(self.kind, uuid7(), title, detail) for title in titles]
        self.hits.extend(held)
        return held


def sources() -> dict[SearchKind, FakeSource]:
    """One empty source per kind, in `SearchKind`'s order, sharing one log."""
    log: list[Asked] = []
    return {kind: FakeSource(kind, log=log) for kind in SearchKind}
