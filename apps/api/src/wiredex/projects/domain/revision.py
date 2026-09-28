"""A revision: one stage of a project (`A - breadboard`), what its BOM, netlist and firmware
line will hang from (ADR 0003).

Its project and workspace always come from the project it is drafted in or the revision it is
forked from, never from an argument that could disagree with them.
"""

from dataclasses import dataclass
from datetime import datetime

from wiredex.projects.domain.errors import RevisionContentLockedError, RevisionInUseError
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.values import (
    Notes,
    ProjectId,
    RevisionId,
    RevisionLabel,
    RevisionStatus,
    Summary,
    WorkspaceId,
)


@dataclass(frozen=True, slots=True)
class RevisionDetails:
    """Everything editable about a revision, as one comparable value."""

    label: RevisionLabel
    summary: Summary | None = None
    notes: Notes | None = None


@dataclass(eq=False)
class Revision:
    """One stage of a project, named by its label and summary."""

    id: RevisionId
    workspace_id: WorkspaceId
    project_id: ProjectId
    label: RevisionLabel
    summary: Summary | None
    notes: Notes | None
    status: RevisionStatus
    forked_from: RevisionId | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def draft(
        cls, revision_id: RevisionId, project: Project, details: RevisionDetails, now: datetime
    ) -> Revision:
        """A new draft of the project, forked from nothing."""
        return cls(
            id=revision_id,
            workspace_id=project.workspace_id,
            project_id=project.id,
            label=details.label,
            summary=details.summary,
            notes=details.notes,
            status=RevisionStatus.DRAFT,
            forked_from=None,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def fork_of(
        cls, source: Revision, revision_id: RevisionId, details: RevisionDetails, now: datetime
    ) -> Revision:
        """A new draft of the source's project, remembering the source.

        Whatever the source's status (requirement 6.5): the next stage starts from what was
        built. The summary and notes are the fork's own, never the source's.
        """
        return cls(
            id=revision_id,
            workspace_id=source.workspace_id,
            project_id=source.project_id,
            label=details.label,
            summary=details.summary,
            notes=details.notes,
            status=RevisionStatus.DRAFT,
            forked_from=source.id,
            created_at=now,
            updated_at=now,
        )

    @property
    def details(self) -> RevisionDetails:
        return RevisionDetails(self.label, self.summary, self.notes)

    def revise(self, details: RevisionDetails, now: datetime) -> bool:
        """Replaces label, summary and notes whole, in any status (requirement 4.8).

        Whether the label is free is the project's revisions' to say, before this. Returns
        whether anything changed, so a no-op commits nothing.
        """
        if self.details == details:
            return False
        self.label = details.label
        self.summary = details.summary
        self.notes = details.notes
        self.updated_at = now
        return True

    def ensure_deletable(self) -> None:
        """Only a draft goes (requirement 5.3): a reserved, built or dismantled revision is the
        record of stock that moved for it."""
        if self.status is not RevisionStatus.DRAFT:
            raise RevisionInUseError(
                f"revision {self.label} is {self.status}, and only a draft can be deleted"
            )

    def ensure_content_editable(self) -> None:
        """Refuses anything but a draft, naming the status (decision 11): a reserved, built or
        dismantled revision's BOM is the record of that build. 11's netlist asks it too."""
        if self.status is not RevisionStatus.DRAFT:
            raise RevisionContentLockedError(
                f"revision {self.label} is {self.status}, and only a draft's content can change"
            )

    def touch(self, now: datetime) -> None:
        """Its content changed: the revision's last change moves, and the project's last
        activity with it (requirement 5.3)."""
        self.updated_at = now
