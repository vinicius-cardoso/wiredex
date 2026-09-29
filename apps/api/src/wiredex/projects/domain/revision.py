"""A revision: one stage of a project (`A - breadboard`), what its BOM, netlist and firmware
line will hang from (ADR 0003).

Its project and workspace always come from the project it is drafted in or the revision it is
forked from, never from an argument that could disagree with them.
"""

from dataclasses import dataclass
from datetime import datetime

from wiredex.projects.domain.errors import RevisionContentLockedError, RevisionHoldsStockError
from wiredex.projects.domain.lifecycle import (
    Transition,
    TransitionNotAllowedError,
    step_for,
)
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

    def ensure_allows(self, transition: Transition) -> None:
        """Refuse a transition the lifecycle table has no row for, naming the status and the
        transition (requirement 1.2). Each transition's first check after the lock, before any
        stock is read."""
        if step_for(self.status, transition) is None:
            raise TransitionNotAllowedError(
                f"revision {self.label} is {self.status}, which does not allow {transition}",
                transition,
                self.status,
            )

    def move(self, transition: Transition, now: datetime) -> None:
        """Set the status to the row's target and stamp `updated_at` with `now`, the instant
        the stock write stamped, so the revision's last change and its movements carry one
        time (requirement 1.3). Refused as `ensure_allows`, so no use case moves a revision the
        table refuses."""
        step = step_for(self.status, transition)
        if step is None:
            raise TransitionNotAllowedError(
                f"revision {self.label} is {self.status}, which does not allow {transition}",
                transition,
                self.status,
            )
        self.status = step.target
        self.updated_at = now

    def ensure_deletable(self) -> None:
        """A revision that holds stock can't go; a draft or a dismantled one can (decision 7,
        widening 08's requirement 5.3). The refusal says what frees it: cancelling the
        reservation for a reserved revision, dismantling the build for a built one (9.1)."""
        if self.status.holds_stock:
            raise RevisionHoldsStockError(
                f"revision {self.label} is {self.status}; {_free_first(self.status)} first"
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


def _free_first(status: RevisionStatus) -> str:
    """What frees a held revision, for the delete refusal: cancelling a reservation, or
    dismantling a build (requirement 9.1)."""
    if status is RevisionStatus.RESERVED:
        return "cancel the reservation"
    return "dismantle the build"
