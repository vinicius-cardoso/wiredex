from datetime import UTC, datetime
from uuid import uuid7

import pytest

from wiredex.inventory.domain.errors import UnitHeldError
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import (
    Mac,
    PartId,
    RevisionId,
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
    revision_id: RevisionId | None = None,
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
        revision_id=revision_id,
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

    def test_retiring_a_held_unit_is_refused(self) -> None:
        # Requirement 3.8: a build holds a reserved or in-use unit; retiring hears what frees it.
        for status in (UnitStatus.RESERVED, UnitStatus.IN_USE):
            u = unit(status=status)
            with pytest.raises(UnitHeldError):
                u.retire()
            assert u.status is status


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

    def test_unretiring_a_held_unit_is_refused(self) -> None:
        # Decision 5: un-retire acts only on a retired unit, so a held one isn't put back
        # in stock — it hears what frees it instead (requirement 3.8).
        for status in (UnitStatus.RESERVED, UnitStatus.IN_USE):
            u = unit(status=status)
            with pytest.raises(UnitHeldError):
                u.unretire()
            assert u.status is status


class TestBuildMoves:
    """Reserve, release, build and return: the four moves a transition drives (decision 5)."""

    def test_reserve_for_links_the_revision_and_marks_it_reserved(self) -> None:
        # Requirement 3.1: an in-stock unit becomes reserved, linked to the revision.
        revision = RevisionId(uuid7())
        u = unit(status=UnitStatus.IN_STOCK)

        u.reserve_for(revision)

        assert u.status is UnitStatus.RESERVED
        assert u.revision_id == revision

    def test_release_clears_the_link_and_returns_it_to_stock(self) -> None:
        # Requirement 3.7: a cancelled reservation frees its units.
        u = unit(status=UnitStatus.RESERVED, revision_id=RevisionId(uuid7()))

        u.release()

        assert u.status is UnitStatus.IN_STOCK
        assert u.revision_id is None

    def test_build_keeps_the_link_and_marks_it_in_use(self) -> None:
        # Requirement 3.6: a built unit keeps its revision; its lot_id stays.
        revision = RevisionId(uuid7())
        lot = StockLotId(uuid7())
        u = unit(lot_id=lot, status=UnitStatus.RESERVED, revision_id=revision)

        u.build()

        assert u.status is UnitStatus.IN_USE
        assert u.revision_id == revision
        assert u.lot_id == lot

    def test_return_to_clears_the_link_and_lands_in_the_return_lot(self) -> None:
        # Requirement 3.7: a dismantled build's units land in the chosen location's lot.
        return_lot = StockLotId(uuid7())
        u = unit(status=UnitStatus.IN_USE, revision_id=RevisionId(uuid7()))

        u.return_to(return_lot)

        assert u.status is UnitStatus.IN_STOCK
        assert u.revision_id is None
        assert u.lot_id == return_lot

    def test_each_move_refuses_the_wrong_starting_status(self) -> None:
        # RevisionStock reaches a move only with a unit it locked in that status; any other
        # is a bug, not a refusal (a ValueError, not an InventoryError).
        with pytest.raises(ValueError, match="in-stock"):
            unit(status=UnitStatus.RESERVED).reserve_for(RevisionId(uuid7()))
        with pytest.raises(ValueError, match="reserved"):
            unit(status=UnitStatus.IN_STOCK).release()
        with pytest.raises(ValueError, match="reserved"):
            unit(status=UnitStatus.IN_STOCK).build()
        with pytest.raises(ValueError, match="in-use"):
            unit(status=UnitStatus.RESERVED).return_to(StockLotId(uuid7()))


class TestEnsureFree:
    def test_ensure_movable_refuses_a_held_unit_naming_what_frees_it(self) -> None:
        # Requirement 3.8: the message says whether to cancel or dismantle.
        reserved = unit(status=UnitStatus.RESERVED)
        with pytest.raises(UnitHeldError, match="cancel the reservation"):
            reserved.ensure_movable()
        in_use = unit(status=UnitStatus.IN_USE)
        with pytest.raises(UnitHeldError, match="dismantle the build"):
            in_use.ensure_movable()

    def test_ensure_movable_allows_an_in_stock_or_retired_unit(self) -> None:
        unit(status=UnitStatus.IN_STOCK).ensure_movable()
        unit(status=UnitStatus.RETIRED).ensure_movable()

    def test_ensure_deletable_refuses_a_held_unit(self) -> None:
        with pytest.raises(UnitHeldError):
            unit(status=UnitStatus.RESERVED).ensure_deletable()
        with pytest.raises(UnitHeldError):
            unit(status=UnitStatus.IN_USE).ensure_deletable()


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
