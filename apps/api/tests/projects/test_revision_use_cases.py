"""The revision use cases and the fork over the in-memory projects fakes.

The fakes write straight into their stores and count commits, so a refused change is one that
left the stores as they were and committed nothing. They can't roll back, so a fork whose copy
fails is judged by its commits here; the integration suite shows the rollback itself.
"""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import uuid7

import anyio
import pytest
from hypothesis import given
from hypothesis import strategies as st

from support.projects import (
    BENCH,
    NOW,
    Copy,
    CopyFailedError,
    FailingContent,
    RecordingContent,
    World,
)
from wiredex.projects.application.ports import NewRevision, RevisionContent
from wiredex.projects.domain.errors import (
    DuplicateRevisionLabelError,
    LastRevisionError,
    NoLabelLeftError,
    ProjectNotFoundError,
    ProjectsError,
    RevisionHoldsStockError,
    RevisionNotFoundError,
)
from wiredex.projects.domain.project import Project, ProjectDetails
from wiredex.projects.domain.project_revisions import ProjectRevisions
from wiredex.projects.domain.revision import Revision, RevisionDetails
from wiredex.projects.domain.values import (
    Notes,
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    RevisionStatus,
    Summary,
)

pytestmark = pytest.mark.anyio

type Snapshot = dict[RevisionId, tuple[object, ...]]


def snapshot(world: World) -> Snapshot:
    """Every stored revision as plain values, so a later comparison sees any change."""
    return {
        revision.id: (
            revision.project_id,
            revision.label,
            revision.summary,
            revision.notes,
            revision.status,
            revision.forked_from,
            revision.created_at,
            revision.updated_at,
        )
        for revision in world.work.revisions.saved.values()
    }


def of_project(world: World, project: Project) -> ProjectRevisions:
    return ProjectRevisions(
        tuple(r for r in world.work.revisions.saved.values() if r.project_id == project.id)
    )


class TestAdd:
    async def test_takes_the_label_summary_and_notes_given_as_a_draft(self) -> None:
        # Requirement 4.1, under the project's lock.
        world = World()
        project = world.hold_project("Weather station")
        world.clock.advance(timedelta(minutes=5))

        revision = await world.add_revision(
            BENCH,
            project.id,
            NewRevision(RevisionLabel("v2"), Summary("first PCB"), Notes("Order from JLC.")),
        )

        assert world.work.revisions.saved[revision.id] is revision
        assert revision.details == RevisionDetails(
            RevisionLabel("v2"), Summary("first PCB"), Notes("Order from JLC.")
        )
        assert revision.project_id == project.id
        assert revision.workspace_id == BENCH
        assert revision.status is RevisionStatus.DRAFT
        assert revision.forked_from is None
        assert revision.created_at == NOW + timedelta(minutes=5)
        assert world.work.projects.locks == [project.id]
        assert world.work.commits == 1

    async def test_without_a_label_takes_the_suggestion(self) -> None:
        # Requirement 4.4: B is the latest, so C.
        world = World()
        project = world.hold_project("Weather station")
        world.hold_revision(project, "B", minutes=1)

        revision = await world.add_revision(BENCH, project.id, NewRevision())

        assert revision.label == RevisionLabel("C")

    async def test_refuses_a_label_a_sibling_holds_in_another_case(self) -> None:
        # Requirement 4.3; the refusal names the project and the label as it is held.
        world = World()
        project = world.hold_project("Weather station")
        world.hold_revision(project, "B", minutes=1)
        before = snapshot(world)

        with pytest.raises(
            DuplicateRevisionLabelError, match=r"^Weather station already has a revision B$"
        ):
            await world.add_revision(BENCH, project.id, NewRevision(RevisionLabel("b")))

        assert snapshot(world) == before
        assert world.work.commits == 0

    async def test_without_a_label_is_refused_when_none_is_left(self) -> None:
        # Requirement 4.6: sixteen Zs have no successor within 16 characters.
        world = World()
        project = world.hold_project("Weather station", revision="Z" * 16)

        with pytest.raises(NoLabelLeftError, match="give the revision a label"):
            await world.add_revision(BENCH, project.id, NewRevision())

        assert world.work.commits == 0


class TestUpdate:
    async def test_refuses_a_label_a_sibling_holds_in_another_case(self) -> None:
        # Requirement 4.3, under the project's lock.
        world = World()
        project = world.hold_project("Weather station")
        second = world.hold_revision(project, "B", minutes=1)
        before = snapshot(world)

        with pytest.raises(DuplicateRevisionLabelError, match="already has a revision A"):
            await world.update_revision(BENCH, second.id, RevisionDetails(RevisionLabel("a")))

        assert snapshot(world) == before
        assert world.work.projects.locks == [project.id]
        assert world.work.commits == 0

    async def test_keeps_its_own_label_in_another_case(self) -> None:
        world = World()
        project = world.hold_project("Weather station", revision="rev-a")
        [revision] = world.work.revisions.saved.values()
        world.clock.advance(timedelta(minutes=5))

        edited = await world.update_revision(
            BENCH, revision.id, RevisionDetails(RevisionLabel("REV-A"), Summary("breadboard"))
        )

        assert edited is revision
        assert revision.details == RevisionDetails(RevisionLabel("REV-A"), Summary("breadboard"))
        assert revision.updated_at == NOW + timedelta(minutes=5)
        assert world.work.projects.locks == [project.id]
        assert world.work.commits == 1

    async def test_edits_a_revision_in_any_status_and_needs_no_lock_for_the_label_it_has(
        self,
    ) -> None:
        # Requirement 4.8: a built revision's summary and notes can still be written.
        world = World()
        project = world.hold_project("Weather station")
        built = world.hold_revision(project, "B", status=RevisionStatus.BUILT, minutes=1)

        await world.update_revision(
            BENCH, built.id, RevisionDetails(RevisionLabel("B"), notes=Notes("Sensor moved."))
        )

        assert built.notes == Notes("Sensor moved.")
        assert built.status is RevisionStatus.BUILT
        assert world.work.projects.locks == []
        assert world.work.commits == 1

    async def test_an_edit_that_changes_nothing_commits_nothing(self) -> None:
        world = World()
        project = world.hold_project("Weather station")
        revision = world.hold_revision(project, "B", minutes=1)
        revision.summary = Summary("perfboard")
        world.clock.advance(timedelta(minutes=5))

        await world.update_revision(
            BENCH, revision.id, RevisionDetails(RevisionLabel("B"), Summary("perfboard"))
        )

        assert revision.updated_at == NOW + timedelta(minutes=1)
        assert world.work.commits == 0


class TestDelete:
    async def test_removes_a_draft_and_touches_its_project(self) -> None:
        # Requirement 5.1; the touch is what keeps the deletion in the list's last activity.
        world = World()
        project = world.hold_project("Weather station")
        second = world.hold_revision(project, "B", minutes=1)
        world.clock.advance(timedelta(minutes=5))

        await world.delete_revision(BENCH, second.id)

        assert [r.label.value for r in world.work.revisions.saved.values()] == ["A"]
        assert project.updated_at == NOW + timedelta(minutes=5)
        assert world.work.projects.locks == [project.id]
        assert world.work.commits == 1

    async def test_refuses_the_only_revision(self) -> None:
        # Requirement 5.2.
        world = World()
        world.hold_project("Weather station")
        [only] = world.work.revisions.saved.values()

        with pytest.raises(LastRevisionError, match="delete the project instead"):
            await world.delete_revision(BENCH, only.id)

        assert only.id in world.work.revisions.saved
        assert world.work.commits == 0

    async def test_refuses_a_revision_that_isnt_a_draft(self) -> None:
        # Requirement 5.3, with a built revision placed in the fakes.
        world = World()
        project = world.hold_project("Weather station")
        built = world.hold_revision(project, "B", status=RevisionStatus.BUILT, minutes=1)

        with pytest.raises(RevisionHoldsStockError, match="revision B is built"):
            await world.delete_revision(BENCH, built.id)

        assert built.id in world.work.revisions.saved
        assert project.updated_at == NOW
        assert world.work.commits == 0

    async def test_deleting_a_forks_source_keeps_the_fork_and_clears_its_source(self) -> None:
        # Requirement 5.4.
        world = World()
        project = world.hold_project("Weather station")
        [source] = world.work.revisions.saved.values()
        fork = await world.fork_revision(BENCH, source.id, NewRevision())

        await world.delete_revision(BENCH, source.id)

        assert world.work.revisions.saved == {fork.id: fork}
        assert fork.forked_from is None
        assert of_project(world, project).latest is fork


class TestFork:
    async def test_records_its_source_and_takes_the_suggestion(self) -> None:
        # Requirement 6.1: a draft of the same project, B after A, its summary its own.
        world = World()
        project = world.hold_project("Weather station")
        [source] = world.work.revisions.saved.values()
        source.summary = Summary("breadboard")
        world.clock.advance(timedelta(minutes=5))

        fork = await world.fork_revision(BENCH, source.id, NewRevision(summary=Summary("perf")))

        assert world.work.revisions.saved[fork.id] is fork
        assert fork.forked_from == source.id
        assert fork.project_id == project.id
        assert fork.label == RevisionLabel("B")
        assert fork.summary == Summary("perf")
        assert fork.created_at == NOW + timedelta(minutes=5)
        assert source.summary == Summary("breadboard")
        assert world.work.projects.locks == [project.id]
        assert world.work.commits == 1

    async def test_a_fork_of_a_built_revision_is_a_draft(self) -> None:
        # Requirement 6.5: the next stage starts from what was built.
        world = World()
        project = world.hold_project("Weather station")
        built = world.hold_revision(project, "B", status=RevisionStatus.BUILT, minutes=1)

        fork = await world.fork_revision(BENCH, built.id, NewRevision(RevisionLabel("C")))

        assert fork.status is RevisionStatus.DRAFT
        assert fork.forked_from == built.id
        assert built.status is RevisionStatus.BUILT

    async def test_copies_every_content_in_order_before_its_one_commit(self) -> None:
        # Requirements 6.2 and 6.7: the contents come from the unit of work, not the use case.
        world = World()
        world.hold_project("Weather station")
        [source] = world.work.revisions.saved.values()
        log: list[Copy] = []
        bom = RecordingContent(world.work, "bom", log)
        nets = RecordingContent(world.work, "nets", log)
        world.work.revision_contents = (bom, nets)

        fork = await world.fork_revision(BENCH, source.id, NewRevision())

        assert log == [Copy("bom", source.id, fork.id, 0), Copy("nets", source.id, fork.id, 0)]
        assert world.work.commits == 1

    async def test_a_content_that_fails_means_no_commit(self) -> None:
        # Requirement 6.4, as far as the fakes can tell; the rollback is the integration
        # suite's.
        world = World()
        world.hold_project("Weather station")
        [source] = world.work.revisions.saved.values()
        log: list[Copy] = []
        after = RecordingContent(world.work, "after", log)
        world.work.revision_contents = (FailingContent(), after)

        with pytest.raises(CopyFailedError):
            await world.fork_revision(BENCH, source.id, NewRevision())

        assert log == []
        assert world.work.commits == 0


async def test_get_answers_the_revision() -> None:
    world = World()
    world.hold_project("Weather station")
    [revision] = world.work.revisions.saved.values()

    assert await world.get_revision(BENCH, revision.id) is revision
    assert world.work.opened_for == [BENCH]


async def test_adding_to_a_project_not_in_the_workspace_is_not_found() -> None:
    world = World()
    world.hold_project("Weather station")

    with pytest.raises(ProjectNotFoundError, match="that project doesn't exist"):
        await world.add_revision(BENCH, ProjectId(uuid7()), NewRevision())

    assert world.work.commits == 0


def _get(world: World, revision_id: RevisionId) -> Awaitable[object]:
    return world.get_revision(BENCH, revision_id)


def _fork(world: World, revision_id: RevisionId) -> Awaitable[object]:
    return world.fork_revision(BENCH, revision_id, NewRevision())


def _relabel(world: World, revision_id: RevisionId) -> Awaitable[object]:
    return world.update_revision(BENCH, revision_id, RevisionDetails(RevisionLabel("Z")))


def _delete(world: World, revision_id: RevisionId) -> Awaitable[object]:
    return world.delete_revision(BENCH, revision_id)


_ON_A_REVISION = pytest.mark.parametrize(
    "action", [_get, _fork, _relabel, _delete], ids=["get", "fork", "relabel", "delete"]
)


@_ON_A_REVISION
async def test_a_revision_not_in_the_workspace_is_not_found(
    action: Callable[[World, RevisionId], Awaitable[object]],
) -> None:
    # Requirement 5.6.
    world = World()
    world.hold_project("Weather station")

    with pytest.raises(RevisionNotFoundError, match="that revision doesn't exist"):
        await action(world, RevisionId(uuid7()))

    assert world.work.commits == 0


@pytest.mark.parametrize("action", [_fork, _relabel, _delete], ids=["fork", "relabel", "delete"])
async def test_a_revision_deleted_while_waiting_for_the_lock_is_not_found(
    action: Callable[[World, RevisionId], Awaitable[object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Decision 15: the revision read before the lock is looked for again after it, so a
    # concurrent delete is a 404 rather than a fork of nothing or a second delete.
    world = World()
    project = world.hold_project("Weather station")
    second = world.hold_revision(project, "B", minutes=1)
    take_the_lock = world.work.projects.locked

    async def locked_after_a_delete(project_id: ProjectId) -> Project | None:
        await world.work.revisions.remove(second)
        return await take_the_lock(project_id)

    monkeypatch.setattr(world.work.projects, "locked", locked_after_a_delete)

    with pytest.raises(RevisionNotFoundError, match="that revision doesn't exist"):
        await action(world, second.id)

    assert world.work.commits == 0


# --- Property 5: a project keeps its revisions' invariants --------------------------------

# Labels a sequence keeps colliding on, in both cases; None asks for the suggestion when
# adding or forking, and keeps the revision's own label when relabelling.
_ASKED = st.none() | st.sampled_from(("A", "a", "B", "b", "C", "v1", "V1", "v2"))
_STEPS = st.lists(
    st.tuples(
        st.sampled_from(("add", "fork", "relabel", "delete")),
        _ASKED,
        st.integers(0, 9),  # which revision, counted from the oldest
        st.booleans(),  # whether the clock moves first; when it doesn't, the id breaks ties
    ),
    max_size=12,
)


async def _step(world: World, project: Project, kind: str, asked: str | None, pick: int) -> bool:
    """Runs one step; whether it would be a no-op if accepted, so it should commit nothing."""
    label = None if asked is None else RevisionLabel(asked)
    alive = of_project(world, project).items
    target = alive[pick % len(alive)]
    match kind:
        case "add":
            await world.add_revision(BENCH, project.id, NewRevision(label))
        case "fork":
            await world.fork_revision(BENCH, target.id, NewRevision(label))
        case "relabel":
            details = RevisionDetails(label or target.label, target.summary, target.notes)
            no_op = details == target.details
            await world.update_revision(BENCH, target.id, details)
            return no_op
        case _:
            await world.delete_revision(BENCH, target.id)
    return False


@given(steps=_STEPS)
def test_a_project_keeps_its_revisions_invariants(
    steps: list[tuple[str, str | None, int, bool]],
) -> None:
    """Property 5: a project keeps its revisions' invariants.

    For any sequence of operations on one project (adding, forking and relabelling with no
    label, a free one or a taken one in any case, and deleting any of its revisions), after
    every step the project has at least one revision, its labels are distinct when folded,
    every revision is a draft, the latest is the one created last, and no forked_from names a
    revision that is gone. A refused step changes nothing and commits nothing; an accepted one
    commits exactly once (a relabel to the label it has changes nothing, so it commits none).

    **Validates: Requirements 1.1, 4.1, 4.3, 4.9, 4.10, 5.1, 5.2, 5.4**
    """

    async def scenario() -> None:
        world = World()
        view = await world.create_project(BENCH, ProjectDetails(ProjectName("Weather station")))
        project = view.project
        created: list[RevisionId] = [revision.id for revision in view.revisions.items]

        for kind, asked, pick, moves in steps:
            if moves:
                world.clock.advance(timedelta(minutes=1))
            before, commits = snapshot(world), world.work.commits
            try:
                no_op = await _step(world, project, kind, asked, pick)
            except ProjectsError:
                assert snapshot(world) == before
                assert world.work.commits == commits
            else:
                assert world.work.commits == commits + (0 if no_op else 1)
                created += [r for r in world.work.revisions.saved if r not in before]

            revisions = of_project(world, project).items
            assert revisions
            assert len({r.label.fold() for r in revisions}) == len(revisions)
            assert all(r.status is RevisionStatus.DRAFT for r in revisions)
            alive = {r.id for r in revisions}
            assert of_project(world, project).latest == _last_created(world, created, alive)
            assert all(r.forked_from is None or r.forked_from in alive for r in revisions)

    anyio.run(scenario)


def _last_created(world: World, created: list[RevisionId], alive: set[RevisionId]) -> Revision:
    newest = next(revision_id for revision_id in reversed(created) if revision_id in alive)
    return world.work.revisions.saved[newest]


# --- Property 6: a fork adds one draft and copies every content once, in order ------------


@given(
    statuses=st.lists(st.sampled_from(RevisionStatus), min_size=1, max_size=4),
    pick=st.integers(0, 3),
    asked=st.none() | st.sampled_from(("a", "B", "E", "v2")),
    contents=st.integers(0, 3),
    failing_at=st.none() | st.integers(0, 3),
)
def test_a_fork_adds_one_draft_and_copies_every_content_once_in_order(
    statuses: list[RevisionStatus],
    pick: int,
    asked: str | None,
    contents: int,
    failing_at: int | None,
) -> None:
    """Property 6: a fork adds one draft and copies every content once, in order.

    For any project with any revisions, any source revision in any of the four statuses, and
    any number of registered contents, forking adds exactly one revision: a draft of the same
    project, labelled as asked or as suggested, forked from the source. Every content's copy is
    called exactly once, with the source and the fork, in the order the contents were
    registered, before the single commit; the source and every other revision are unchanged;
    and when a content raises, nothing is committed.

    **Validates: Requirements 6.1, 6.2, 6.3, 6.5, 6.7**
    """

    async def scenario() -> None:
        world = World()
        project = world.hold_project("Weather station", revision=None)
        held = [
            world.hold_revision(project, chr(ord("A") + number), status=status, minutes=number)
            for number, status in enumerate(statuses)
        ]
        source = held[pick % len(held)]
        log: list[Copy] = []
        names = [f"content {number}" for number in range(contents)]
        registered: list[RevisionContent] = [
            RecordingContent(world.work, name, log) for name in names
        ]
        failing = failing_at is not None and failing_at <= contents
        if failing_at is not None and failing:
            registered.insert(failing_at, FailingContent())
        world.work.revision_contents = registered
        world.clock.advance(timedelta(minutes=10))
        label = None if asked is None else RevisionLabel(asked)
        taken = label is not None and label.fold() in {r.label.fold() for r in held}
        before = snapshot(world)

        if taken:
            with pytest.raises(DuplicateRevisionLabelError):
                await world.fork_revision(BENCH, source.id, NewRevision(label))
            assert snapshot(world) == before
            assert log == []
            assert world.work.commits == 0
            return
        if failing:
            with pytest.raises(CopyFailedError):
                await world.fork_revision(BENCH, source.id, NewRevision(label))
            assert [copy.content for copy in log] == names[:failing_at]
            assert world.work.commits == 0
            return

        fork = await world.fork_revision(BENCH, source.id, NewRevision(label))

        assert set(world.work.revisions.saved) - set(before) == {fork.id}
        assert fork.status is RevisionStatus.DRAFT
        assert fork.project_id == project.id
        assert fork.forked_from == source.id
        expected = label or ProjectRevisions(tuple(held)).suggested_label()
        assert fork.label == expected
        assert log == [Copy(name, source.id, fork.id, 0) for name in names]
        assert world.work.commits == 1
        assert {k: v for k, v in snapshot(world).items() if k != fork.id} == before

    anyio.run(scenario)
