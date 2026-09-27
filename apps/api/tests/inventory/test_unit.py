from datetime import UTC, datetime
from uuid import uuid7

from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import (
    Mac,
    PartId,
    Serial,
    ShortCode,
    StockLotId,
    UnitId,
    WorkspaceId,
)

NOW = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
PART = PartId(uuid7())

_next_code = iter(range(1, 10_000))


def unit(
    *,
    lot_id: StockLotId | None = None,
    serial: Serial | None = None,
    mac: Mac | None = None,
    status: UnitStatus = UnitStatus.IN_STOCK,
) -> Unit:
    return Unit(
        id=UnitId(uuid7()),
        workspace_id=BENCH,
        part_id=PART,
        lot_id=lot_id if lot_id is not None else StockLotId(uuid7()),
        code=ShortCode.for_unit(next(_next_code)),
        serial=serial,
        mac=mac,
        status=status,
        created_at=NOW,
    )


class TestRelabel:
    def test_setting_a_serial_and_mac_reports_a_change(self) -> None:
        u = unit()

        assert u.relabel(Serial("SN-1"), Mac("aa:bb:cc:dd:ee:ff"))
        assert u.serial == Serial("SN-1")
        assert u.mac == Mac("aa:bb:cc:dd:ee:ff")

    def test_clearing_a_serial_and_mac_reports_a_change(self) -> None:
        u = unit(serial=Serial("SN-1"), mac=Mac("aa:bb:cc:dd:ee:ff"))

        assert u.relabel(None, None)
        assert u.serial is None
        assert u.mac is None

    def test_relabelling_to_the_same_values_changes_nothing(self) -> None:
        # Requirement 5.6: the use case skips the commit on a False.
        u = unit(serial=Serial("SN-1"), mac=Mac("aa:bb:cc:dd:ee:ff"))

        assert not u.relabel(Serial("SN-1"), Mac("AA-BB-CC-DD-EE-FF"))
        assert u.serial == Serial("SN-1")
        assert u.mac == Mac("aa:bb:cc:dd:ee:ff")

    def test_changing_only_the_serial_reports_a_change(self) -> None:
        u = unit(serial=Serial("SN-1"), mac=Mac("aa:bb:cc:dd:ee:ff"))

        assert u.relabel(Serial("SN-2"), Mac("aa:bb:cc:dd:ee:ff"))
        assert u.serial == Serial("SN-2")


class TestRetire:
    def test_retiring_an_in_stock_unit_reports_a_change(self) -> None:
        # Requirement 3.1: the use case pairs this with an ADJUST -1.
        u = unit(status=UnitStatus.IN_STOCK)

        assert u.retire()
        assert u.status is UnitStatus.RETIRED

    def test_retiring_an_already_retired_unit_changes_nothing(self) -> None:
        # Requirement 3.6: no status write, no compensating movement.
        u = unit(status=UnitStatus.RETIRED)

        assert not u.retire()
        assert u.status is UnitStatus.RETIRED


class TestUnretire:
    def test_unretiring_a_retired_unit_reports_a_change(self) -> None:
        # Requirement 3.2: the use case pairs this with an ADJUST +1.
        u = unit(status=UnitStatus.RETIRED)

        assert u.unretire()
        assert u.status is UnitStatus.IN_STOCK

    def test_unretiring_an_in_stock_unit_changes_nothing(self) -> None:
        # Requirement 3.6: no status write, no compensating movement.
        u = unit(status=UnitStatus.IN_STOCK)

        assert not u.unretire()
        assert u.status is UnitStatus.IN_STOCK


class TestMoveTo:
    def test_moving_repoints_the_lot(self) -> None:
        destination = StockLotId(uuid7())
        u = unit()

        u.move_to(destination)

        assert u.lot_id == destination

    def test_a_retired_unit_still_repoints_when_asked(self) -> None:
        # The entity just follows its lot; refusing a retired move is the use case's guard
        # (requirement 4.5), not the entity's, so move_to itself is unconditional.
        destination = StockLotId(uuid7())
        u = unit(status=UnitStatus.RETIRED)

        u.move_to(destination)

        assert u.lot_id == destination
