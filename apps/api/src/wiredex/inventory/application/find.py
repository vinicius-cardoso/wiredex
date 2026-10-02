"""Finding a unit or a location by a bit of its text, for the palette (19-command-palette).

Each is one read in inventory's own transaction, closed before it answers: the workspace's live
records whose identifying text contains the text, case aside, the ones whose title starts with it
first, then by title, at most `limit` (decisions 1 and 2). A blank text finds nothing rather than
everything. The caller bounds the limit: the search route takes at most 20.
"""

from wiredex.inventory.application.units import UnitOfWorkFactory
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.unit import Unit
from wiredex.inventory.domain.values import WorkspaceId


class FindUnits:
    """The units whose code, serial or MAC holds the text, by code; a unit in the trash is
    absent (16-soft-delete-and-trash, decision 2)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, text: str, limit: int) -> list[Unit]:
        needle = text.strip()
        if not needle:
            return []
        async with self._unit_of_work(workspace_id) as work:
            return await work.units.find(needle, limit)


class FindLocations:
    """The locations whose name or short code holds the text, by name."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, text: str, limit: int) -> list[Location]:
        needle = text.strip()
        if not needle:
            return []
        async with self._unit_of_work(workspace_id) as work:
            return await work.locations.find(needle, limit)
