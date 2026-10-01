"""A project: something being built, described once by its name, description and tags.

What a project holds beyond that lives in its revisions (ADR 0003), so the entity owns only its
own details and when they last changed.
"""

from dataclasses import dataclass, field
from datetime import datetime

from wiredex.projects.domain.values import (
    Description,
    ProjectId,
    ProjectName,
    Tags,
    WorkspaceId,
)


@dataclass(frozen=True, slots=True)
class ProjectDetails:
    """Everything editable about a project, as one value.

    One object, so starting and revising take the same fields, and comparing it is how
    `revise` knows nothing changed.
    """

    name: ProjectName
    description: Description | None = None
    tags: Tags = field(default_factory=Tags.none)


@dataclass(eq=False)
class Project:
    """A weather station, a greenhouse controller: what its revisions are stages of."""

    id: ProjectId
    workspace_id: WorkspaceId
    name: ProjectName
    description: Description | None
    tags: Tags
    created_at: datetime
    updated_at: datetime
    # When it moved to the trash, None while it is live (16-soft-delete-and-trash, decision 1).
    trashed_at: datetime | None = None

    @classmethod
    def start(
        cls,
        project_id: ProjectId,
        workspace_id: WorkspaceId,
        details: ProjectDetails,
        now: datetime,
    ) -> Project:
        """A new project, created and last updated at the same instant."""
        return cls(
            id=project_id,
            workspace_id=workspace_id,
            name=details.name,
            description=details.description,
            tags=details.tags,
            created_at=now,
            updated_at=now,
        )

    @property
    def details(self) -> ProjectDetails:
        return ProjectDetails(self.name, self.description, self.tags)

    def revise(self, details: ProjectDetails, now: datetime) -> bool:
        """Replaces the details whole (requirement 1.5).

        Returns whether anything changed, so an edit that changes nothing commits nothing and
        doesn't move the project up the list.
        """
        if self.details == details:
            return False
        self.name = details.name
        self.description = details.description
        self.tags = details.tags
        self.updated_at = now
        return True

    def touch(self, now: datetime) -> None:
        """A revision of it was deleted.

        Every other revision change shows in the revisions' own dates, which the list reads for
        a project's last activity (decision 11); a deleted revision leaves no date behind, so
        its project keeps it instead.
        """
        self.updated_at = now

    def move_to_trash(self, now: datetime) -> None:
        """Out of every list and lookup until it is restored (16-soft-delete-and-trash,
        decision 1). Its revisions, their BOMs and their netlists go with it.

        Nothing else changes, its last update included, so a restored project comes back as it
        was, where its list had it.
        """
        self.trashed_at = now

    def restore_from_trash(self) -> None:
        """Back in every list and lookup it was in, as it was (16's requirement 5.1)."""
        self.trashed_at = None

    @property
    def in_trash(self) -> bool:
        return self.trashed_at is not None
