"""Finding a project by a bit of its name, for the palette (19-command-palette).

One read in the projects' own transaction, closed before it answers: the workspace's live
projects whose name contains the text, case aside, the ones starting with it first, then by
name, at most `limit` (decisions 1 and 2). A blank text finds nothing rather than everything.
The caller bounds the limit: the search route takes at most 20.
"""

from wiredex.projects.application.projects import UnitOfWorkFactory
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.values import WorkspaceId


class FindProjects:
    """The projects whose name holds the text; a project in the trash is absent, its revisions
    with it (16-soft-delete-and-trash, decision 2)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, text: str, limit: int) -> list[Project]:
        needle = text.strip()
        if not needle:
            return []
        async with self._unit_of_work(workspace_id) as work:
            return await work.projects.find(needle, limit)
