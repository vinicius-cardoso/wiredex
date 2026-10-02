"""What the search gives over HTTP, in primitives only: no domain object reaches a field, and the
`from_*` classmethods do the converting, as every module's schemas do."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel

from wiredex.search.domain.search import SearchGroup, SearchHit, SearchKind, SearchResults

# The kinds spelled out for the wire, so the generated client gets a union it can switch on. A
# test keeps this list in step with `SearchKind`, as the other modules do for their enums.
type SearchKindName = Literal["part", "unit", "project", "firmware", "category", "location"]


class SearchHitResponse(BaseModel):
    """One record found: a part's name with its manufacturer and part number, a unit's code with
    its part's name, a project's name with its tags, a firmware's name with its target, a
    category's name, a location's name with its code (requirement 1.2)."""

    id: UUID
    title: str
    detail: str | None

    @classmethod
    def from_hit(cls, hit: SearchHit) -> Self:
        return cls(id=hit.id, title=hit.title, detail=hit.detail)


class SearchGroupResponse(BaseModel):
    """One kind's hits, the closest first, and whether more match than it holds (1.3, 1.4)."""

    kind: SearchKindName
    hits: list[SearchHitResponse]
    more: bool

    @classmethod
    def from_group(cls, found: SearchGroup) -> Self:
        return cls(
            kind=kind_name(found.kind),
            hits=[SearchHitResponse.from_hit(hit) for hit in found.hits],
            more=found.more,
        )


class SearchResultsResponse(BaseModel):
    """What the workspace answered for the text, trimmed: a group per kind that found something,
    parts first, then units, projects, firmware, categories and locations (requirement 1.3)."""

    query: str
    groups: list[SearchGroupResponse]

    @classmethod
    def from_results(cls, found: SearchResults) -> Self:
        return cls(
            query=found.text, groups=[SearchGroupResponse.from_group(one) for one in found.groups]
        )


def kind_name(kind: SearchKind) -> SearchKindName:
    # mypy reads an enum's value as the literals its members hold, so a seventh kind stops
    # type-checking here until the wire contract above lists it too.
    name: SearchKindName = kind.value
    return name
