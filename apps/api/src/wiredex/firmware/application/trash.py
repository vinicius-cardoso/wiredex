"""Firmware's share of the trash: the firmware in it, and bringing one back or deleting it for good.

Moving a firmware to the trash is `DeleteFirmware`, refused while a flash names one of its versions
(16-soft-delete-and-trash, decision 4). What follows it is here, one use case each, which bootstrap
wraps in the trash module's bin for firmware (decision 8). A firmware's versions, their files and
its links have no state of their own: they are in the trash with it and come back with it.
Restoring and deleting for good each lock the firmware first, so the two take turns and the
second finds nothing (decision 10).
"""

from wiredex.firmware.application.firmware import UnitOfWorkFactory
from wiredex.firmware.application.ports import FirmwareUnitOfWork
from wiredex.firmware.domain.errors import FirmwareNotFoundError
from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.values import FirmwareId, WorkspaceId
from wiredex.shared_kernel.domain.trash import TrashedSlice


class ListTrashedFirmware:
    """The newest `count` firmware in the trash, only those whose name or target holds the text
    when there is one, and how many match in all (requirement 4.1)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, count: int, text: str | None = None
    ) -> TrashedSlice[Firmware]:
        async with self._unit_of_work(workspace_id) as work:
            return await work.firmwares.trashed(count, text)


class RestoreFirmware:
    """A firmware back from the trash with its versions and links, as it was (5.1)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, firmware_id: FirmwareId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            firmware = await _in_trash(work, firmware_id)
            firmware.restore_from_trash()
            await work.commit()


class DeleteFirmwareForGood:
    """A firmware in the trash deleted with its versions, their files and its links, as deleting
    a firmware did before (requirement 6.1)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, firmware_id: FirmwareId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            firmware = await _in_trash(work, firmware_id)
            await work.firmwares.remove(firmware)
            await work.commit()


class EmptyFirmwareTrash:
    """Every firmware in the trash deleted for good, in one statement (requirement 6.4)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId) -> int:
        async with self._unit_of_work(workspace_id) as work:
            emptied = await work.firmwares.empty_trash()
            await work.commit()
            return emptied


async def _in_trash(work: FirmwareUnitOfWork, firmware_id: FirmwareId) -> Firmware:
    """The firmware, locked, if it is in the trash; a 404 for one that isn't, another
    workspace's included (requirements 5.3, 6.2)."""
    firmware = await work.firmwares.in_trash(firmware_id)
    if firmware is None:
        raise FirmwareNotFoundError("that firmware isn't in the trash")
    return firmware
