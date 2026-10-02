"""Finding a firmware by a bit of its name or target, for the palette (19-command-palette).

One read in the firmware's own transaction, closed before it answers: the workspace's live
firmware whose name or board target contains the text, case aside, the ones whose name starts
with it first, then by name, at most `limit` (decisions 1 and 2). A blank text finds nothing
rather than everything. The caller bounds the limit: the search route takes at most 20.
"""

from wiredex.firmware.application.firmware import UnitOfWorkFactory
from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.values import WorkspaceId


class FindFirmware:
    """The firmware whose name or target holds the text; a firmware in the trash is absent, its
    versions with it (16-soft-delete-and-trash, decision 2)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, text: str, limit: int) -> list[Firmware]:
        needle = text.strip()
        if not needle:
            return []
        async with self._unit_of_work(workspace_id) as work:
            return await work.firmwares.find(needle, limit)
