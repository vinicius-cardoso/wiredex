from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.projects.domain.errors import (
    DuplicateRevisionLabelError,
    LastRevisionError,
    NoLabelLeftError,
    RevisionInUseError,
)
from wiredex.projects.domain.project_revisions import ProjectRevisions
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import (
    MAX_LABEL_LENGTH,
    ProjectId,
    RevisionId,
    RevisionLabel,
    RevisionStatus,
    WorkspaceId,
)

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
PROJECT = ProjectId(uuid7())


def a_revision(
    label: str,
    minutes: int = 0,
    status: RevisionStatus = RevisionStatus.DRAFT,
    revision_id: UUID | None = None,
) -> Revision:
    # Built field by field: a revision in a status other than draft can't be made through
    # the domain until 10-build-lifecycle.
    created = NOW + timedelta(minutes=minutes)
    return Revision(
        id=RevisionId(revision_id or uuid7()),
        workspace_id=BENCH,
        project_id=PROJECT,
        label=RevisionLabel(label),
        summary=None,
        notes=None,
        status=status,
        forked_from=None,
        created_at=created,
        updated_at=created,
    )


def revisions(*items: Revision) -> ProjectRevisions:
    return ProjectRevisions(items)


class TestLatest:
    def test_is_the_one_created_last_whatever_the_order_given(self) -> None:
        first, second, third = a_revision("A", 0), a_revision("C", 1), a_revision("B", 2)

        siblings = revisions(second, third, first)

        assert siblings.latest is third
        assert siblings.items == (first, second, third)

    def test_breaks_a_tie_on_the_clock_by_id(self) -> None:
        # UUIDv7 ids are time-ordered, so the greater id is the one written later.
        earlier = a_revision("A", revision_id=UUID(int=1))
        later = a_revision("B", revision_id=UUID(int=2))

        assert revisions(later, earlier).latest is later

    def test_is_none_before_the_first_revision(self) -> None:
        assert revisions().latest is None


class TestSuggestedLabel:
    def test_is_a_for_a_project_with_none(self) -> None:
        assert revisions().suggested_label() == RevisionLabel("A")

    def test_steps_the_latest_label(self) -> None:
        assert revisions(a_revision("v1", 0), a_revision("v2", 1)).suggested_label() == (
            RevisionLabel("v3")
        )

    def test_steps_on_past_labels_taken_in_any_case(self) -> None:
        # B was forked after C existed, so it is the latest, and C and d are both taken.
        siblings = revisions(
            a_revision("A", 0), a_revision("c", 1), a_revision("D", 2), a_revision("B", 3)
        )

        assert siblings.suggested_label() == RevisionLabel("E")

    def test_is_none_when_the_latest_cant_be_stepped(self) -> None:
        assert revisions(a_revision("Z" * MAX_LABEL_LENGTH)).suggested_label() is None


class TestLabelFor:
    def test_answers_the_suggestion_when_none_is_asked(self) -> None:
        assert revisions(a_revision("A")).label_for(None) == RevisionLabel("B")

    def test_refuses_a_label_a_sibling_holds_in_another_case(self) -> None:
        with pytest.raises(DuplicateRevisionLabelError, match="already has a revision Rev-B"):
            revisions(a_revision("A", 0), a_revision("Rev-B", 1)).label_for(RevisionLabel("rev-b"))

    def test_accepts_a_free_label(self) -> None:
        assert revisions(a_revision("A")).label_for(RevisionLabel("pcb1")) == (
            RevisionLabel("pcb1")
        )

    def test_keeps_a_revisions_own_label_on_a_relabel(self) -> None:
        own = a_revision("B", 1)
        siblings = revisions(a_revision("A", 0), own)

        assert siblings.label_for(RevisionLabel("b"), renaming=own) == RevisionLabel("b")

    def test_refuses_a_siblings_label_on_a_relabel(self) -> None:
        own = a_revision("B", 1)
        siblings = revisions(a_revision("A", 0), own)

        with pytest.raises(DuplicateRevisionLabelError):
            siblings.label_for(RevisionLabel("a"), renaming=own)

    def test_refuses_when_no_label_is_left(self) -> None:
        with pytest.raises(NoLabelLeftError, match="give the revision a label"):
            revisions(a_revision("9" * MAX_LABEL_LENGTH)).label_for(None)


class TestRemoving:
    def test_the_only_revision_is_kept(self) -> None:
        only = a_revision("A")

        with pytest.raises(LastRevisionError, match="delete the project instead"):
            revisions(only).ensure_removable(only)

    def test_a_built_revision_is_kept(self) -> None:
        built = a_revision("A", 0, RevisionStatus.BUILT)

        with pytest.raises(RevisionInUseError, match="revision A is built"):
            revisions(built, a_revision("B", 1)).ensure_removable(built)

    def test_a_draft_with_siblings_can_go(self) -> None:
        draft = a_revision("A", 0)

        revisions(draft, a_revision("B", 1, RevisionStatus.BUILT)).ensure_removable(draft)

    def test_a_project_of_drafts_can_be_deleted(self) -> None:
        revisions(a_revision("A", 0), a_revision("B", 1)).ensure_all_deletable()

    @pytest.mark.parametrize(
        "status", [RevisionStatus.RESERVED, RevisionStatus.BUILT, RevisionStatus.DISMANTLED]
    )
    def test_a_project_holding_anything_but_drafts_is_kept(self, status: RevisionStatus) -> None:
        siblings = revisions(a_revision("A", 0), a_revision("B", 1, status))

        with pytest.raises(RevisionInUseError, match=f"revision B is {status}"):
            siblings.ensure_all_deletable()


def test_includes_answers_whether_a_revision_is_among_them() -> None:
    first = a_revision("A")

    assert revisions(first).includes(first.id)
    assert not revisions(first).includes(RevisionId(uuid7()))


# --- Property 4: a suggested label is always free --------------------------------------

_LABELS = st.one_of(
    st.from_regex(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,6}[A-Za-z0-9])?", fullmatch=True),
    # Near the cap, where a chain of successors runs out.
    st.builds(
        lambda prefix, run: (prefix + run * MAX_LABEL_LENGTH)[:MAX_LABEL_LENGTH],
        st.sampled_from(["", "v", "rev-", "1."]),
        st.sampled_from(["Z", "z", "9"]),
    ),
    st.builds(
        lambda run, last: run * (MAX_LABEL_LENGTH - 1) + last,
        st.sampled_from(["Z", "9"]),
        st.sampled_from(["X", "Y", "7", "8"]),
    ),
)


def _chain(start: str, length: int) -> list[str]:
    """The start and up to `length` of its successors, what a project stepping its labels
    holds, so the suggestion often has to step past several."""
    labels = [start]
    current: RevisionLabel | None = RevisionLabel(start)
    for _ in range(length):
        assert current is not None
        current = current.successor()
        if current is None:
            break
        labels.append(current.value)
    return labels


@st.composite
def _histories(draw: st.DrawFn) -> ProjectRevisions:
    pool = _chain(draw(_LABELS), draw(st.integers(0, 6))) + draw(st.lists(_LABELS, max_size=4))
    chosen = draw(st.lists(st.sampled_from(pool), unique_by=str.lower, max_size=len(pool)))
    # A narrow clock, so ties on created_at happen and the id has to break them.
    minutes = draw(st.lists(st.integers(0, 3), min_size=len(chosen), max_size=len(chosen)))
    ids = draw(st.permutations(range(1, len(chosen) + 1)))
    return ProjectRevisions(
        tuple(
            a_revision(label, minute, revision_id=UUID(int=number))
            for label, minute, number in zip(chosen, minutes, ids, strict=True)
        )
    )


@given(siblings=_histories())
def test_a_suggested_label_is_always_free(siblings: ProjectRevisions) -> None:
    """Property 4: a suggested label is always free.

    For any revisions of one project with distinct labels, the suggestion is A when there are
    none, and is otherwise held by no revision of the project, folded, and equal to the latest
    revision's successor whenever that successor is free; when no label is left within 16
    characters, there is no suggestion, and adding a revision without a label is refused.

    **Validates: Requirements 4.4, 4.5, 4.6**
    """
    suggested = siblings.suggested_label()
    latest = siblings.latest
    if latest is None:
        assert suggested == RevisionLabel("A")
        return
    taken = {revision.label.fold() for revision in siblings.items}
    successor = latest.label.successor()
    if suggested is None:
        # Every label the chain reaches before it passes 16 characters is taken.
        candidate = successor
        while candidate is not None:
            assert candidate.fold() in taken
            candidate = candidate.successor()
        with pytest.raises(NoLabelLeftError):
            siblings.label_for(None)
        return
    assert suggested.fold() not in taken
    if successor is not None and successor.fold() not in taken:
        assert suggested == successor
    assert siblings.label_for(None) == suggested
