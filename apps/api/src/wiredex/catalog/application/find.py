"""Finding a part or a category by a bit of its text, for the palette (19-command-palette).

Each is one read in the catalog's own transaction, closed before it answers: the workspace's
live records whose identifying text contains the text, case aside, the ones whose name starts
with it first, then by name, at most `limit` (decisions 1 and 2). A blank text finds nothing
rather than everything. The caller bounds the limit: the search route takes at most 20.
"""

from wiredex.catalog.application.categories import UnitOfWorkFactory
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.values import WorkspaceId


class FindParts:
    """The parts whose name, MPN or manufacturer holds the text; a part in the trash is absent
    (16-soft-delete-and-trash, decision 2)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, text: str, limit: int
    ) -> list[PartDefinition]:
        needle = text.strip()
        if not needle:
            return []
        async with self._unit_of_work(workspace_id) as work:
            return await work.parts.find(needle, limit)


class FindCategories:
    """The categories whose name holds the text."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, text: str, limit: int) -> list[Category]:
        needle = text.strip()
        if not needle:
            return []
        async with self._unit_of_work(workspace_id) as work:
            return await work.categories.find(needle, limit)
