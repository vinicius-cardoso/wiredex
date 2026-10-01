import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from uuid import UUID, uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.firmware.domain.errors import (
    FirmwareError,
    FirmwareField,
    FirmwareRefusal,
    FirmwareRefusalError,
    FlashedInFutureError,
    InvalidNotesError,
    NotReleasedError,
    UnitRetiredError,
)
from wiredex.firmware.domain.firmware import Firmware, FirmwareDetails
from wiredex.firmware.domain.flash import (
    FUTURE_ALLOWANCE,
    MAX_NOTES_LENGTH,
    MAX_UNIT_CODE_LENGTH,
    Flash,
    FlashDetails,
    FlashLog,
    FlashNotes,
    UnitCode,
    UnitFacts,
)
from wiredex.firmware.domain.semver import SemVer
from wiredex.firmware.domain.source import SourceFile, SourceFiles, SourcePath, SourceText
from wiredex.firmware.domain.values import (
    BoardTarget,
    Changelog,
    FirmwareId,
    FirmwareName,
    FlashId,
    Framework,
    RevisionId,
    SourceFileId,
    UnitId,
    VersionId,
    WorkspaceId,
)
from wiredex.firmware.domain.version import FirmwareVersion

NOW = datetime(2026, 9, 30, 3, 0, tzinfo=UTC)
RELEASED = NOW - timedelta(days=2)
BENCH = WorkspaceId(uuid7())
GREENHOUSE_A = RevisionId(uuid7())

PICO_BLINK = Firmware.start(
    FirmwareId(uuid7()),
    BENCH,
    FirmwareDetails(FirmwareName("Pico blink"), BoardTarget("RPI_PICO"), Framework.MICROPYTHON),
    NOW - timedelta(days=30),
)
BLINK = SourceFiles.of(
    [SourceFile(SourceFileId(uuid7()), SourcePath("main.py"), SourceText("led.toggle()\n"))]
)
CHECKING = FlashNotes("Checking a new board")


def a_draft(number: str = "1.1.0") -> FirmwareVersion:
    return FirmwareVersion.draft(
        VersionId(uuid7()), PICO_BLINK, SemVer.parse(number), None, NOW - timedelta(days=3)
    )


def a_release(number: str = "1.0.0") -> FirmwareVersion:
    """A version drafted, given a changelog and released: the only way the domain makes one."""
    version = a_draft(number)
    version.revise(version.number, Changelog("Blinks the LED once a second."), RELEASED)
    version.release(BLINK, RELEASED)
    return version


def a_unit(
    code: str = "WX-U-0002", *, retired: bool = False, revision_id: RevisionId | None = None
) -> UnitFacts:
    return UnitFacts(UnitId(uuid7()), UnitCode(code), retired, revision_id)


def a_flash(
    unit: UnitFacts,
    version: FirmwareVersion,
    flashed_at: datetime | None = None,
    notes: FlashNotes | None = None,
    now: datetime = NOW,
) -> Flash:
    return Flash.record(FlashId(uuid7()), unit, version, FlashDetails(flashed_at, notes), now)


def _when(flash: Flash) -> tuple[datetime, datetime, UUID]:
    """Decision 4's order, spelled out rather than read from `Flash.order`."""
    return (flash.flashed_at, flash.created_at, flash.id)


class TestRecord:
    def test_records_the_unit_the_version_the_time_and_the_notes(self) -> None:
        # Requirements 1.1 and 1.8: the code is copied, so the entry outlives the unit.
        pico, version = a_unit(), a_release()
        at = NOW - timedelta(hours=2)

        flash = a_flash(pico, version, at, CHECKING)

        assert (flash.unit_id, flash.unit_code, flash.version_id) == (
            pico.unit_id,
            UnitCode("WX-U-0002"),
            version.id,
        )
        assert (flash.flashed_at, flash.notes, flash.created_at) == (at, CHECKING, NOW)
        assert flash.workspace_id == version.workspace_id == BENCH
        assert flash.revision_id is None

    def test_a_flash_logged_without_a_time_was_flashed_now(self) -> None:
        # Requirement 1.2.
        flash = a_flash(a_unit(), a_release())

        assert flash.flashed_at == flash.created_at == NOW
        assert flash.notes is None

    def test_a_time_before_the_version_was_released_is_recorded(self) -> None:
        # Requirement 1.3: the board may have run the code before it was released here.
        before = RELEASED - timedelta(days=5)

        assert a_flash(a_unit(), a_release(), before).flashed_at == before

    def test_five_minutes_ahead_is_taken_and_one_second_more_refused(self) -> None:
        # Requirement 1.4: a phone's clock a little ahead of the server's.
        ahead = NOW + timedelta(minutes=5)

        assert a_flash(a_unit(), a_release(), ahead).flashed_at == ahead
        with pytest.raises(FlashedInFutureError, match="five minutes") as refused:
            a_flash(a_unit(), a_release(), ahead + timedelta(seconds=1))
        assert refused.value.code is FirmwareRefusal.FLASHED_IN_FUTURE
        assert refused.value.field is FirmwareField.FLASHED_AT

    def test_a_draft_is_refused_on_the_version(self) -> None:
        # Requirement 1.5: a draft can still change, so the entry could stop meaning the code.
        with pytest.raises(NotReleasedError, match=re.escape("1.1.0 is a draft")) as refused:
            a_flash(a_unit(), a_draft("1.1.0"))
        assert refused.value.code is FirmwareRefusal.NOT_RELEASED
        assert refused.value.field is FirmwareField.VERSION
        assert refused.value.item == "1.1.0"

    def test_a_retired_unit_is_refused_on_the_unit(self) -> None:
        # Requirement 1.6: the refusal says how to flash it all the same.
        with pytest.raises(UnitRetiredError, match="WX-U-0003 is retired: un-retire it") as refused:
            a_flash(a_unit("WX-U-0003", retired=True), a_release())
        assert refused.value.code is FirmwareRefusal.UNIT_RETIRED
        assert refused.value.field is FirmwareField.UNIT
        assert refused.value.item == "WX-U-0003"

    def test_a_held_units_revision_is_recorded_and_kept(self) -> None:
        # Requirement 1.7: once the build is cancelled the unit names no revision, and the
        # entry still names the one it was flashed in.
        esp32 = a_unit("WX-U-0001", revision_id=GREENHOUSE_A)

        flash = a_flash(esp32, a_release())
        freed = replace(esp32, revision_id=None)

        assert flash.revision_id == GREENHOUSE_A
        assert a_flash(freed, a_release()).revision_id is None
        assert flash.revision_id == GREENHOUSE_A

    def test_orders_by_when_it_was_flashed_then_logged_then_by_id(self) -> None:
        flash = a_flash(a_unit(), a_release(), RELEASED)

        assert flash.order() == (RELEASED, NOW, flash.id)


class TestFlashNotes:
    def test_are_trimmed_and_have_their_whitespace_collapsed(self) -> None:
        assert FlashNotes("  Bench test\t before \n the build ").value == (
            "Bench test before the build"
        )

    def test_accept_their_cap_and_refuse_one_character_more(self) -> None:
        notes = "x" * MAX_NOTES_LENGTH

        assert FlashNotes(notes).value == notes
        with pytest.raises(InvalidNotesError, match="between 1 and 500 characters") as refused:
            FlashNotes(notes + "x")
        assert refused.value.code is FirmwareRefusal.INVALID_NOTES
        assert refused.value.field is FirmwareField.NOTES

    @pytest.mark.parametrize("text", ["", "   ", "\t\n"])
    def test_blank_is_never_notes(self, text: str) -> None:
        # The edge reads blank notes as none before they get here (requirement 1.9).
        with pytest.raises(InvalidNotesError):
            FlashNotes(text)

    @pytest.mark.parametrize("text", ["flashed\x00twice", "bell\x07", "del\x7f"])
    def test_refuse_a_control_character(self, text: str) -> None:
        with pytest.raises(InvalidNotesError, match="control character"):
            FlashNotes(text)

    def test_refuse_half_of_a_surrogate_pair_and_say_so_in_utf_8(self) -> None:
        half: str = json.loads('"\\ud800"')

        with pytest.raises(InvalidNotesError, match="surrogate pair") as refused:
            FlashNotes(f"flashed {half}")
        str(refused.value).encode()


class TestUnitCode:
    @pytest.mark.parametrize("code", ["WX-U-0042", "WX-U-10000", "wx-u-0042"])
    def test_is_kept_as_given(self, code: str) -> None:
        # Inventory minted it, so firmware neither normalizes nor checks its shape.
        assert str(UnitCode(code)) == code

    def test_holds_16_characters_and_refuses_one_more(self) -> None:
        code = "WX-U-" + "9" * (MAX_UNIT_CODE_LENGTH - 5)

        assert UnitCode(code).value == code
        with pytest.raises(FirmwareError, match="between 1 and 16 characters"):
            UnitCode(code + "9")
        with pytest.raises(FirmwareError):
            UnitCode("")


class TestFlashLog:
    def test_a_unit_never_flashed_runs_nothing_known(self) -> None:
        assert FlashLog.of([]) == FlashLog()
        assert FlashLog().current is None

    def test_a_flash_backdated_to_last_week_takes_its_place_without_becoming_current(self) -> None:
        pico = a_unit()
        current = a_flash(pico, a_release("1.1.0"), NOW - timedelta(days=1))
        backdated = a_flash(pico, a_release("1.0.0"), NOW - timedelta(days=7), now=NOW)

        log = FlashLog.of([backdated, current])

        assert log.items == (current, backdated)
        assert log.current is current

    def test_two_flashes_at_one_time_order_by_when_they_were_logged(self) -> None:
        pico = a_unit()
        first = a_flash(pico, a_release("1.0.0"), RELEASED, now=NOW)
        second = a_flash(pico, a_release("1.1.0"), RELEASED, now=NOW + timedelta(minutes=1))

        assert FlashLog.of([second, first]).current is second
        assert FlashLog.of([first, second]).current is second


# --- Properties 1 to 3 ------------------------------------------------------------------------

BOARD = a_unit("WX-U-0002")
RELEASES = (a_release("1.0.0"), a_release("1.1.0"))
# Small pools, so flashes often share a time, a logging time or both, and the id decides.
_FLASHED_AT = st.none() | st.sampled_from([NOW - timedelta(days=2), NOW - timedelta(days=1), NOW])
_LOGGED_AT = st.sampled_from([NOW, NOW + timedelta(hours=1), NOW + timedelta(days=1)])


@st.composite
def _flashes(draw: st.DrawFn, min_size: int = 0) -> list[Flash]:
    """A unit's flashes as the domain records them, each of a release, with distinct ids."""
    ids = draw(st.lists(st.uuids(), min_size=min_size, max_size=6, unique=True))
    return [
        Flash.record(
            FlashId(flash_id),
            BOARD,
            draw(st.sampled_from(RELEASES)),
            FlashDetails(draw(_FLASHED_AT)),
            draw(_LOGGED_AT),
        )
        for flash_id in ids
    ]


@given(flashes=_flashes(), data=st.data())
def test_the_current_version_is_the_newest_flash(flashes: list[Flash], data: st.DataObject) -> None:
    """Property 1: the current version is the newest flash.

    For any flashes of a unit, given in any order, FlashLog.current is the flash with the
    greatest (flashed_at, created_at, id), and the log lists every flash once, in that order,
    newest first.

    **Validates: Requirements 2.1, 2.2**
    """
    log = FlashLog.of(data.draw(st.permutations(flashes)))

    assert sorted(flash.id for flash in log.items) == sorted(flash.id for flash in flashes)
    assert all(_when(newer) > _when(older) for newer, older in pairwise(log.items))
    assert log.current == max(flashes, key=_when, default=None)


@given(data=st.data())
def test_removing_a_flash_leaves_the_newest_of_the_rest(data: st.DataObject) -> None:
    """Property 2: removing a flash leaves the newest of the rest.

    For any flashes and any one of them removed, the current flash is the greatest of those
    left, or none when none is left: removing the current one makes the one before it current,
    and removing any other leaves the current one where it was.

    **Validates: Requirements 3.2**
    """
    flashes = data.draw(_flashes(min_size=1))
    removed = data.draw(st.sampled_from(flashes))
    before = FlashLog.of(flashes)
    rest = [flash for flash in flashes if flash.id != removed.id]

    after = FlashLog.of(rest)

    assert after.current == max(rest, key=_when, default=None)
    if removed == before.current:
        assert after.current == next(iter(before.items[1:]), None)
    else:
        assert after.current == before.current


_OFFSETS = st.sampled_from(
    [FUTURE_ALLOWANCE, FUTURE_ALLOWANCE + timedelta(seconds=1)]
) | st.timedeltas(min_value=timedelta(days=-60), max_value=timedelta(hours=1))
_NOTES = st.none() | st.sampled_from([CHECKING, FlashNotes("Bench test before the build")])


def _refusal(*, released: bool, retired: bool, ahead: timedelta | None) -> type[Exception] | None:
    """What Flash.record refuses, in its order: a draft, a retired unit, then the time."""
    if not released:
        return NotReleasedError
    if retired:
        return UnitRetiredError
    if ahead is not None and ahead > FUTURE_ALLOWANCE:
        return FlashedInFutureError
    return None


@given(
    released=st.booleans(),
    retired=st.booleans(),
    held=st.booleans(),
    ahead=st.none() | _OFFSETS,
    notes=_NOTES,
)
def test_a_flash_refuses_what_it_must(
    released: bool, retired: bool, held: bool, ahead: timedelta | None, notes: FlashNotes | None
) -> None:
    """Property 3: a flash refuses what it must.

    For any unit and version, Flash.record refuses exactly a draft, a retired unit and a time
    past five minutes ahead of now, and otherwise records the unit's code and, while it is
    held, its revision.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8**
    """
    unit = a_unit("WX-U-0001", retired=retired, revision_id=GREENHOUSE_A if held else None)
    version = a_release() if released else a_draft()
    flashed_at = None if ahead is None else NOW + ahead
    details = FlashDetails(flashed_at, notes)
    refusal = _refusal(released=released, retired=retired, ahead=ahead)

    if refusal is not None:
        with pytest.raises(FirmwareRefusalError) as refused:
            Flash.record(FlashId(uuid7()), unit, version, details, NOW)
        assert type(refused.value) is refusal
    else:
        flash = Flash.record(FlashId(uuid7()), unit, version, details, NOW)
        assert (flash.unit_id, flash.unit_code, flash.version_id) == (
            unit.unit_id,
            UnitCode("WX-U-0001"),
            version.id,
        )
        assert flash.revision_id == (GREENHOUSE_A if held else None)
        assert flash.flashed_at == (NOW if flashed_at is None else flashed_at)
        assert (flash.notes, flash.created_at) == (notes, NOW)
