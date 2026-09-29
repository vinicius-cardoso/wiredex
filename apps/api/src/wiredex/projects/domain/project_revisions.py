"""One project's revisions, and the rules that look across siblings: which is the latest, which
label comes next, and which may go.

Built from the one read a repository makes, under the project's lock when it is about to
change them (decision 15), so what it answers holds until the transaction ends.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from wiredex.projects.domain.errors import (
    DuplicateRevisionLabelError,
    LastRevisionError,
    NoLabelLeftError,
)
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import RevisionId, RevisionLabel


def _created_order(revision: Revision) -> tuple[datetime, UUID]:
    # The id breaks a tie on the clock: UUIDv7 ids are time-ordered, so the later one sorts
    # last (decision 3).
    return (revision.created_at, revision.id)


@dataclass(frozen=True, slots=True)
class ProjectRevisions:
    """One project's revisions, oldest first."""

    items: tuple[Revision, ...]

    def __post_init__(self) -> None:
        # Sorted here rather than trusted from the caller, so `latest` and the order the page
        # shows can't depend on how a repository happened to read the rows.
        object.__setattr__(self, "items", tuple(sorted(self.items, key=_created_order)))

    @property
    def latest(self) -> Revision | None:
        """The one created last (decision 3). None only for a project being created, before
        its revision A exists."""
        return self.items[-1] if self.items else None

    def suggested_label(self) -> RevisionLabel | None:
        """A for none; else the latest's successor, stepped on past every label taken.

        Always ends: each step is a new label (Property 3), and at most as many can be taken
        as there are revisions. None when the chain passes 16 characters first.
        """
        latest = self.latest
        if latest is None:
            return RevisionLabel.first()
        taken = {revision.label.fold() for revision in self.items}
        candidate = latest.label.successor()
        while candidate is not None and candidate.fold() in taken:
            candidate = candidate.successor()
        return candidate

    def label_for(
        self, asked: RevisionLabel | None, renaming: Revision | None = None
    ) -> RevisionLabel:
        """The label asked for, refused when a sibling other than `renaming` holds it folded;
        or the suggestion, refused when there is none (requirements 4.3, 4.4, 4.6)."""
        if asked is None:
            suggested = self.suggested_label()
            if suggested is None:
                raise NoLabelLeftError("give the revision a label")
            return suggested
        for revision in self.items:
            if revision is not renaming and revision.label.fold() == asked.fold():
                raise DuplicateRevisionLabelError(
                    f"this project already has a revision {revision.label}"
                )
        return asked

    def ensure_removable(self, revision: Revision) -> None:
        """The only revision is kept, and only a draft goes (decisions 2 and 5)."""
        if len(self.items) <= 1:
            raise LastRevisionError(
                "a project keeps at least one revision; delete the project instead"
            )
        revision.ensure_deletable()

    def ensure_all_deletable(self) -> None:
        """No revision holding stock, which deleting the project needs (requirements 1.8, 9.3):
        a draft or a dismantled one holds nothing (decision 7). The refusal names the first
        that holds stock, so the owner knows which build to free (requirement 9.3)."""
        for revision in self.items:
            if revision.status.holds_stock:
                revision.ensure_deletable()

    def includes(self, revision_id: RevisionId) -> bool:
        return any(revision.id == revision_id for revision in self.items)
