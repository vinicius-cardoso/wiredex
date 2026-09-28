"""What projects takes and gives over HTTP, in primitives only.

No domain object reaches a field: the `from_*` classmethods do the converting, as catalog's
and inventory's do. Requests carry text as typed; the router turns a blank description,
summary or notes into none and hands the rest to the domain's values, which normalize or
refuse it (design's HTTP API).
"""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field

from wiredex.projects.application.ports import ProjectSummary, ProjectView, TagCount
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import MAX_TAGS, RevisionStatus

# ADR 0003's four states spelled out for the wire, so the generated client gets a union it
# can switch on. A test keeps this in step with the `RevisionStatus` enum.
type RevisionStatusName = Literal["draft", "reserved", "built", "dismantled"]


class CreateProjectRequest(BaseModel):
    """A new project. Its revision A comes with it (design decision 2)."""

    name: str
    description: str | None = None
    # Capped as given, before normalizing: more than twenty texts is a mistake, not a request
    # (design's error table).
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)


class UpdateProjectRequest(BaseModel):
    """A project's name, description and tags, replacing the stored ones whole (1.5)."""

    name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)


class NewRevisionRequest(BaseModel):
    """A revision to add or fork. No label takes the suggested one (decision 4)."""

    label: str | None = None
    summary: str | None = None
    notes: str | None = None


class UpdateRevisionRequest(BaseModel):
    """A revision's label, summary and notes, replacing the stored ones whole (4.8)."""

    label: str
    summary: str | None = None
    notes: str | None = None


class RevisionResponse(BaseModel):
    """A revision on the wire: `A - breadboard` is the label `A` and the summary."""

    id: UUID
    project_id: UUID
    label: str
    summary: str | None
    notes: str | None
    status: RevisionStatusName
    forked_from: UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_revision(cls, revision: Revision) -> Self:
        return cls(
            id=revision.id,
            project_id=revision.project_id,
            label=str(revision.label),
            summary=_text(revision.summary),
            notes=_text(revision.notes),
            status=_status_name(revision.status),
            forked_from=revision.forked_from,
            created_at=revision.created_at,
            updated_at=revision.updated_at,
        )


class RevisionSummaryResponse(BaseModel):
    """The latest revision as a list row shows it: `B - perfboard`, with its status."""

    id: UUID
    label: str
    summary: str | None
    status: RevisionStatusName

    @classmethod
    def from_revision(cls, revision: Revision) -> Self:
        return cls(
            id=revision.id,
            label=str(revision.label),
            summary=_text(revision.summary),
            status=_status_name(revision.status),
        )


class ProjectResponse(BaseModel):
    """A project page (requirement 1.6): its revisions oldest first, the one it opens on, and
    the label a new revision would take, which the fork dialog prefills. `next_label` is null
    only when no label can be suggested within 16 characters."""

    id: UUID
    name: str
    description: str | None
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    revisions: list[RevisionResponse]
    latest_revision_id: UUID
    next_label: str | None

    @classmethod
    def from_view(cls, view: ProjectView, latest: Revision) -> Self:
        """`latest` is passed in rather than read here, because the view types it as
        optional and the router decides what a project with no revision means."""
        project = view.project
        suggested = view.revisions.suggested_label()
        return cls(
            id=project.id,
            name=str(project.name),
            description=_text(project.description),
            tags=_tags(project),
            created_at=project.created_at,
            updated_at=project.updated_at,
            revisions=[RevisionResponse.from_revision(r) for r in view.revisions.items],
            latest_revision_id=latest.id,
            next_label=None if suggested is None else str(suggested),
        )


class ProjectSummaryResponse(BaseModel):
    """A row of the project list (requirement 3.1)."""

    id: UUID
    name: str
    tags: list[str]
    revision_count: int
    latest_revision: RevisionSummaryResponse
    last_activity: datetime

    @classmethod
    def from_summary(cls, summary: ProjectSummary) -> Self:
        return cls(
            id=summary.project.id,
            name=str(summary.project.name),
            tags=_tags(summary.project),
            revision_count=summary.revision_count,
            latest_revision=RevisionSummaryResponse.from_revision(summary.latest),
            last_activity=summary.last_activity,
        )


class ProjectTagResponse(BaseModel):
    """A tag of the workspace and how many projects carry it (requirement 2.6)."""

    tag: str
    projects: int

    @classmethod
    def from_count(cls, count: TagCount) -> Self:
        return cls(tag=str(count.tag), projects=count.projects)


def _status_name(status: RevisionStatus) -> RevisionStatusName:
    # An enum's value is the literal it holds, so a fifth state stops type-checking here
    # until the wire contract above lists it too.
    name: RevisionStatusName = status.value
    return name


def _tags(project: Project) -> list[str]:
    return list(project.tags.texts())


def _text(value: object) -> str | None:
    return None if value is None else str(value)
