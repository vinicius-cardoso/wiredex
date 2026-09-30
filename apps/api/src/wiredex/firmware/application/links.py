"""The revisions a firmware runs on: link one, unlink one, and give a fork its source's.

A link lives in firmware, not among a revision's contents in projects (decision 2): what a
revision runs keeps changing after it is built, so a link is made and removed whatever the
revision's status, and projects' draft lock never applies to it. A link or an unlink locks its
firmware first (decision 8) and moves the firmware's last change only when it changed a link,
so a repeated link or a missing unlink writes nothing.
"""

from datetime import datetime

from wiredex.firmware.application.firmware import (
    RunsOnUnitOfWorkFactory,
    UnitOfWorkFactory,
    load_revision,
    lock_firmware,
)
from wiredex.firmware.application.ports import FirmwareRepositories
from wiredex.firmware.domain.values import FirmwareId, RevisionId, WorkspaceId
from wiredex.shared_kernel.application.ports import Clock


class LinkRevision:
    """Records that a firmware runs on a revision of the workspace (requirement 3.1)."""

    def __init__(self, unit_of_work: RunsOnUnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self, workspace_id: WorkspaceId, firmware_id: FirmwareId, revision_id: RevisionId
    ) -> None:
        async with self._unit_of_work(workspace_id) as work:
            firmware = await lock_firmware(work, firmware_id)
            await load_revision(work, revision_id)
            now = self._clock.now()
            if await work.links.add(firmware.id, revision_id, now):
                firmware.touch(now)
                await work.commit()


class UnlinkRevision:
    """Removes a link, and answers success when there was none (requirement 3.2).

    The revision isn't looked up: a link to one the workspace no longer holds is removed all
    the same, so it refuses nothing (3.6).
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self, workspace_id: WorkspaceId, firmware_id: FirmwareId, revision_id: RevisionId
    ) -> None:
        async with self._unit_of_work(workspace_id) as work:
            firmware = await lock_firmware(work, firmware_id)
            if await work.links.remove(firmware.id, revision_id):
                firmware.touch(self._clock.now())
                await work.commit()


class CopyRevisionLinks:
    """What a fork copies after its BOM and netlist: the firmware its source runs (decision 4).

    Over `FirmwareRepositories`, which bootstrap binds to the fork's session, so it never
    commits: the fork's unit of work does once every content has copied, and a failure anywhere
    keeps no link (requirement 4.3). The fork's links are dated `at`, its creation, and the
    firmware they name move up the list, each now running on one more revision (2.2).
    """

    def __init__(self, work: FirmwareRepositories) -> None:
        self._work = work

    async def copy(self, source: RevisionId, target: RevisionId, at: datetime) -> None:
        await self._work.links.copy(source, target, at)
