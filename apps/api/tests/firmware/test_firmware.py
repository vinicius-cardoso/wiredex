from datetime import UTC, datetime, timedelta
from uuid import uuid7

from wiredex.firmware.domain.firmware import Firmware, FirmwareDetails
from wiredex.firmware.domain.values import (
    BoardTarget,
    FirmwareId,
    FirmwareName,
    Framework,
    WorkspaceId,
)

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=2)
DETAILS = FirmwareDetails(
    FirmwareName("Weather station"), BoardTarget("esp32:esp32:esp32"), Framework.ARDUINO
)


def a_firmware() -> Firmware:
    return Firmware.start(FirmwareId(uuid7()), WorkspaceId(uuid7()), DETAILS, NOW)


def test_a_firmware_moved_to_the_trash_keeps_its_details_and_its_last_change() -> None:
    firmware = a_firmware()
    firmware.move_to_trash(LATER)

    assert firmware.in_trash
    assert firmware.trashed_at == LATER
    assert firmware.details == DETAILS
    assert firmware.updated_at == NOW


def test_a_firmware_restored_from_the_trash_is_live_again_as_it_was() -> None:
    firmware = a_firmware()
    firmware.move_to_trash(LATER)

    firmware.restore_from_trash()

    assert not firmware.in_trash
    assert firmware.trashed_at is None
    assert firmware.updated_at == NOW
