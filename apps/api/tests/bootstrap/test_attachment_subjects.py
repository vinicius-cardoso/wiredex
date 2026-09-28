"""`AttachmentSubjects` over the in-memory catalog and projects (08's decision 12).

Each kind is asked of its own module and read as that kind only: a part's id named as a
project is no project. A subject its module doesn't find is absent, which is what makes an
upload to it a 404 and lets the prune remove its attachments (08's requirements 7.6, 7.8).
"""

from uuid import uuid4

import pytest

from support import catalog, projects
from wiredex.bootstrap.files import AttachmentSubjects
from wiredex.files.domain.values import Subject, SubjectKind, WorkspaceId

pytestmark = pytest.mark.anyio


class Modules:
    """Both modules' fakes, a part and a project with its revision `A`, and the adapter."""

    def __init__(self) -> None:
        self.catalog = catalog.World()
        self.projects = projects.World()
        self.part = self.catalog.add_part(self.catalog.resistors)
        self.project = self.projects.hold_project("Weather station", revision=None)
        self.revision = self.projects.hold_revision(self.project, "A")
        self.subjects = AttachmentSubjects(
            self.catalog.get_part, self.projects.get_project, self.projects.get_revision
        )

    def asked(self) -> tuple[int, int]:
        """How many times each module was opened: catalog's, then projects'."""
        return len(self.catalog.catalog.opened_for), len(self.projects.work.opened_for)


BENCH = WorkspaceId(uuid4())


async def test_a_part_is_asked_of_catalog() -> None:
    modules = Modules()
    assert await modules.subjects.exists(BENCH, Subject(SubjectKind.PART, modules.part.id))
    assert modules.asked() == (1, 0)
    assert modules.catalog.catalog.opened_for == [BENCH]


@pytest.mark.parametrize("kind", [SubjectKind.PROJECT, SubjectKind.REVISION])
async def test_a_project_and_a_revision_are_asked_of_projects(kind: SubjectKind) -> None:
    modules = Modules()
    subject_id = modules.project.id if kind is SubjectKind.PROJECT else modules.revision.id

    assert await modules.subjects.exists(BENCH, Subject(kind, subject_id))
    assert modules.asked() == (0, 1)
    assert modules.projects.work.opened_for == [BENCH]


@pytest.mark.parametrize("kind", list(SubjectKind))
async def test_a_missing_subject_of_each_kind_is_absent(kind: SubjectKind) -> None:
    modules = Modules()
    assert not await modules.subjects.exists(BENCH, Subject(kind, uuid4()))


async def test_an_id_is_read_only_as_its_kind() -> None:
    # A project's id named as a part, or a part's as a project or a revision, is no subject.
    modules = Modules()
    part_id, project_id = modules.part.id, modules.project.id

    assert not await modules.subjects.exists(BENCH, Subject(SubjectKind.PART, project_id))
    assert not await modules.subjects.exists(BENCH, Subject(SubjectKind.PROJECT, part_id))
    assert not await modules.subjects.exists(BENCH, Subject(SubjectKind.REVISION, project_id))
