"""The firmware use cases over the in-memory firmware fakes.

The fakes write straight into their stores and count commits, so a refused change is one that
left the stores as they were and committed nothing.
"""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import uuid7

import pytest

from support.firmware import BENCH, NOW, World
from wiredex.firmware.domain.errors import (
    FirmwareField,
    FirmwareFlashedError,
    FirmwareNotFoundError,
    FirmwareRefusal,
    NameTakenError,
    RevisionNotFoundError,
)
from wiredex.firmware.domain.firmware import FirmwareDetails
from wiredex.firmware.domain.flash import BlockingFlash
from wiredex.firmware.domain.semver import FIRST_VERSION, SemVer
from wiredex.firmware.domain.values import (
    BoardTarget,
    Description,
    FirmwareId,
    FirmwareName,
    Framework,
    RevisionId,
)
from wiredex.firmware.domain.version import VersionStatus

pytestmark = pytest.mark.anyio


def details(
    name: str = "Weather station",
    target: str = "esp32:esp32:esp32",
    framework: Framework = Framework.ARDUINO,
    description: str | None = None,
) -> FirmwareDetails:
    return FirmwareDetails(
        FirmwareName(name),
        BoardTarget(target),
        framework,
        None if description is None else Description(description),
    )


class TestCreate:
    async def test_writes_a_firmware_with_no_versions_in_one_commit(self) -> None:
        # Requirement 1.1: its page offers 0.1.0 for the first version.
        world = World()
        wanted = details(description="Reads the BME280 every five minutes.")

        view = await world.create_firmware(BENCH, wanted)

        assert world.work.commits == 1
        assert world.work.opened_for == [BENCH]
        assert world.work.firmwares.saved == {view.firmware.id: view.firmware}
        assert view.firmware.workspace_id == BENCH
        assert view.firmware.details == wanted
        assert view.firmware.created_at == view.firmware.updated_at == NOW
        assert (view.versions, view.runs_on, view.latest_release) == ((), (), None)
        assert view.suggested == FIRST_VERSION
        assert world.work.links.saved == {}

    async def test_for_a_revision_links_it_in_the_same_commit(self) -> None:
        # Requirement 3.3: the page opens running on it.
        world = World()
        revision = world.directory.hold("Weather station", "A", "breadboard")

        view = await world.create_firmware(BENCH, details(), revision.revision_id)

        assert view.runs_on == (revision,)
        assert world.work.links.saved == {(view.firmware.id, revision.revision_id): NOW}
        assert world.work.commits == 1

    async def test_for_a_revision_the_workspace_doesnt_hold_writes_nothing(self) -> None:
        # Requirement 3.7: the directory holds neither another bench's revision nor a deleted
        # one. The revision is looked up before the name, so the 404 wins over a taken name.
        world = World()
        world.hold_firmware("Weather station")

        with pytest.raises(RevisionNotFoundError, match="that revision doesn't exist"):
            await world.create_firmware(BENCH, details(), RevisionId(uuid7()))

        assert len(world.work.firmwares.saved) == 1
        assert world.work.links.saved == {}
        assert world.work.commits == 0

    async def test_refuses_a_name_another_firmware_holds_naming_it(self) -> None:
        # Requirement 1.3: ignoring case, the message spelling the name as its holder does.
        world = World()
        held = world.hold_firmware("Weather station")
        revision = world.directory.hold()

        with pytest.raises(NameTakenError) as refused:
            await world.create_firmware(BENCH, details("WEATHER  Station"), revision.revision_id)

        assert str(refused.value) == "there is already a firmware named Weather station"
        assert (refused.value.code, refused.value.field) == (
            FirmwareRefusal.NAME_TAKEN,
            FirmwareField.NAME,
        )
        assert refused.value.item == "WEATHER Station"
        assert world.work.firmwares.saved == {held.id: held}
        assert world.work.links.saved == {}
        assert world.work.commits == 0


class TestUpdate:
    async def test_replaces_the_details_whole_under_the_firmwares_lock(self) -> None:
        # Requirement 1.7: the description left out of the edit is gone. The answer is the page.
        world = World()
        firmware = world.hold_firmware("Weather station")
        revision = world.directory.hold()
        world.hold_link(firmware, revision.revision_id)
        world.clock.advance(timedelta(minutes=5))
        edited = details("Weather station S3", "esp32:esp32:esp32s3", Framework.PLATFORMIO)

        view = await world.update_firmware(BENCH, firmware.id, edited)

        assert view.firmware is firmware
        assert firmware.details == edited
        assert firmware.updated_at == NOW + timedelta(minutes=5)
        assert view.runs_on == (revision,)
        assert world.work.firmwares.locks == [firmware.id]
        assert world.work.commits == 1

    async def test_an_edit_that_changes_nothing_commits_nothing(self) -> None:
        world = World()
        firmware = world.hold_firmware("Weather station")
        world.clock.advance(timedelta(minutes=5))

        view = await world.update_firmware(BENCH, firmware.id, details(" Weather  station "))

        assert view.firmware is firmware
        assert firmware.updated_at == NOW
        assert world.work.commits == 0

    async def test_refuses_a_name_another_firmware_holds_naming_it(self) -> None:
        world = World()
        world.hold_firmware("Weather station")
        greenhouse = world.hold_firmware("Greenhouse controller")

        with pytest.raises(NameTakenError, match="a firmware named Weather station"):
            await world.update_firmware(BENCH, greenhouse.id, details("weather station"))

        assert greenhouse.name == FirmwareName("Greenhouse controller")
        assert world.work.commits == 0

    async def test_keeps_its_own_name_in_another_case(self) -> None:
        world = World()
        firmware = world.hold_firmware("Weather station")

        await world.update_firmware(BENCH, firmware.id, details("Weather Station"))

        assert firmware.name == FirmwareName("Weather Station")
        assert world.work.commits == 1


async def test_delete_takes_the_versions_their_files_and_the_links() -> None:
    # Requirement 1.9, in one commit under the firmware's lock; another firmware keeps its own.
    world = World()
    firmware = world.hold_firmware("Weather station")
    release = world.hold_version(firmware, "1.0.0", released=True)
    world.hold_file(release, "weather_station.ino", "void loop() {}\n")
    world.hold_file(world.hold_version(firmware, "1.1.0", based_on=release), "config.h")
    world.hold_link(firmware, world.directory.hold(label="A").revision_id)
    other = world.hold_firmware("Pico blink")
    kept = world.hold_version(other, "1.0.0", released=True)
    kept_file = world.hold_file(kept, "main.py", "led.toggle()\n")
    kept_link = world.directory.hold("Pico board", "A").revision_id
    world.hold_link(other, kept_link)

    await world.delete_firmware(BENCH, firmware.id)

    assert world.work.firmwares.saved == {other.id: other}
    assert world.work.versions.saved == {kept.id: kept}
    assert world.work.sources.saved == {kept_file.id: (kept.id, kept_file)}
    assert world.work.links.saved == {(other.id, kept_link): NOW}
    assert world.work.firmwares.locks == [firmware.id]
    assert world.work.commits == 1


async def test_delete_is_refused_while_a_flash_names_one_of_its_versions() -> None:
    # 15's requirement 5.2: nothing goes, and the refusal names the flashes in the way as a
    # version's does, by the unit's code then newest first, a deleted unit's marked absent.
    # Another firmware's flash isn't in the way.
    world = World()
    firmware = world.hold_firmware("Pico blink")
    first = world.hold_version(firmware, "1.0.0", released=True)
    second = world.hold_version(firmware, "1.1.0", released=True, based_on=first)
    other = world.hold_version(world.hold_firmware("Weather station"), "0.1.0", released=True)
    gone, pico = world.units.hold(), world.units.hold()
    lost = world.hold_flash(gone, first)
    older = world.hold_flash(pico, first, flashed_at=NOW - timedelta(days=1))
    current = world.hold_flash(pico, second)
    world.hold_flash(world.units.hold(), other)
    del world.units.held[gone.unit_id]
    before = world.snapshot()

    with pytest.raises(FirmwareFlashedError) as refused:
        await world.delete_firmware(BENCH, firmware.id)

    assert str(refused.value) == (
        "Pico blink is in the flash logs of 2 boards; remove those entries to delete it"
    )
    assert (refused.value.code, refused.value.item) == (
        FirmwareRefusal.FIRMWARE_FLASHED,
        "Pico blink",
    )
    assert refused.value.flashes == (
        BlockingFlash(lost, first.number, unit_present=False),
        BlockingFlash(current, second.number, unit_present=True),
        BlockingFlash(older, first.number, unit_present=True),
    )
    assert world.snapshot() == before
    assert world.work.firmwares.locks == [firmware.id]
    assert world.work.commits == 0


async def test_get_answers_the_page() -> None:
    # Requirement 1.8: the versions highest first with their status, base, file count and size;
    # the revisions in link order; the latest release under a draft; the successor of 1.2.0.
    world = World()
    firmware = world.hold_firmware("Weather station")
    first = world.hold_version(firmware, "1.0.0", released=True)
    world.hold_file(first, "weather_station.ino", "void setup() {}\n")
    second = world.hold_version(firmware, "1.1.0", released=True, based_on=first)
    world.hold_file(second, "weather_station.ino", "void setup() {}\n")
    world.hold_file(second, "config.h", "#define SDA 21\n")
    draft = world.hold_version(firmware, "1.2.0", based_on=second)
    breadboard = world.directory.hold("Weather station", "A", "breadboard")
    perfboard = world.directory.hold("Weather station", "B", "perfboard")
    world.hold_link(firmware, perfboard.revision_id, minutes=1)
    world.hold_link(firmware, breadboard.revision_id)

    view = await world.get_firmware(BENCH, firmware.id)

    assert view.firmware is firmware
    assert [
        (summary.version, summary.version.status, summary.version.based_on, summary.files)
        for summary in view.versions
    ] == [
        (draft, VersionStatus.DRAFT, second.id, 0),
        (second, VersionStatus.RELEASED, first.id, 2),
        (first, VersionStatus.RELEASED, None, 1),
    ]
    assert [summary.size for summary in view.versions] == [0, 31, 16]
    assert view.runs_on == (breadboard, perfboard)
    assert view.latest_release is second
    assert view.suggested == SemVer(1, 2, 1)
    assert world.work.commits == 0


def _get(world: World, firmware_id: FirmwareId) -> Awaitable[object]:
    return world.get_firmware(BENCH, firmware_id)


def _update(world: World, firmware_id: FirmwareId) -> Awaitable[object]:
    return world.update_firmware(BENCH, firmware_id, details())


def _delete(world: World, firmware_id: FirmwareId) -> Awaitable[object]:
    return world.delete_firmware(BENCH, firmware_id)


@pytest.mark.parametrize("action", [_get, _update, _delete], ids=["get", "update", "delete"])
async def test_a_firmware_not_in_the_workspace_is_not_found(
    action: Callable[[World, FirmwareId], Awaitable[object]],
) -> None:
    # Requirement 1.10: another bench's id reads the same, the fakes holding one bench.
    world = World()
    world.hold_firmware("Weather station")

    with pytest.raises(FirmwareNotFoundError, match="that firmware doesn't exist"):
        await action(world, FirmwareId(uuid7()))

    assert len(world.work.firmwares.saved) == 1
    assert world.work.commits == 0


class TestList:
    async def test_a_row_carries_the_latest_release_and_the_numbers_of_versions_and_drafts(
        self,
    ) -> None:
        # Requirement 2.1: the draft above 1.1.0 doesn't hide it.
        world = World()
        weather = world.hold_firmware("Weather station", minutes=1)
        world.hold_version(weather, "1.0.0", released=True)
        latest = world.hold_version(weather, "1.1.0", released=True)
        world.hold_version(weather, "1.2.0")
        pico = world.hold_firmware("Pico blink", target="RPI_PICO", framework=Framework.MICROPYTHON)

        rows = await world.list_firmware(BENCH)

        assert [(row.firmware, row.latest_release, row.versions, row.drafts) for row in rows] == [
            (weather, latest, 3, 1),
            (pico, None, 0, 0),
        ]
        assert world.work.commits == 0

    async def test_opens_on_the_firmware_changed_last(self) -> None:
        # Requirement 2.2: a link, a version or a file moves its firmware's own date, so the
        # list orders by it; two changed at one instant come newer first.
        world = World()
        oldest = world.hold_firmware("Weather station")
        earlier = world.hold_firmware("Pico blink", minutes=5)
        later = world.hold_firmware("Bench supply", minutes=5)
        newest = world.hold_firmware("Greenhouse controller", minutes=9)

        rows = await world.list_firmware(BENCH)

        assert [row.firmware for row in rows] == [newest, later, earlier, oldest]

    @pytest.mark.parametrize(
        ("text", "names"),
        [
            ("WEATHER", {"Weather station"}),  # in the name, ignoring case
            ("ESP32:esp32", {"Weather station", "Greenhouse controller"}),  # in the target
            ("_", {"Pico blink"}),  # RPI_PICO's underscore, not any one character
            ("%", {"Fan at 50% duty"}),  # a percent sign, not anything at all
            ("  pico ", {"Pico blink"}),  # trimmed, as the project list's search is
        ],
    )
    async def test_narrows_by_name_or_target(self, text: str, names: set[str]) -> None:
        # Requirement 2.3.
        world = World()
        world.hold_firmware("Weather station")
        world.hold_firmware("Greenhouse controller")
        world.hold_firmware("Pico blink", target="RPI_PICO", framework=Framework.MICROPYTHON)
        world.hold_firmware("Fan at 50% duty", target="arduino:avr:uno")

        rows = await world.list_firmware(BENCH, text)

        assert {str(row.firmware.name) for row in rows} == names

    @pytest.mark.parametrize("text", [None, "", "   "])
    async def test_no_text_lists_every_firmware(self, text: str | None) -> None:
        world = World()
        held = {world.hold_firmware("Weather station"), world.hold_firmware("Pico blink")}

        rows = await world.list_firmware(BENCH, text)

        assert {row.firmware for row in rows} == held

    async def test_is_empty_when_nothing_matches(self) -> None:
        # Requirement 2.4.
        world = World()
        world.hold_firmware("Weather station")

        assert await world.list_firmware(BENCH, "greenhouse") == []
        assert await World().list_firmware(BENCH) == []


class TestRevisionFirmware:
    async def test_answers_every_firmware_the_revision_runs_by_name(self) -> None:
        # Requirement 3.4, each row as the list's: by name folded, whatever changed last.
        world = World()
        revision = world.directory.hold("Weather station", "A")
        weather = world.hold_firmware("weather station")
        release = world.hold_version(weather, "1.0.0", released=True)
        world.hold_version(weather, "1.1.0", based_on=release)
        greenhouse = world.hold_firmware("Greenhouse controller", minutes=5)
        pico = world.hold_firmware("Pico blink")
        world.hold_link(weather, revision.revision_id)
        world.hold_link(greenhouse, revision.revision_id, minutes=1)
        world.hold_link(pico, world.directory.hold("Pico board", "A").revision_id)

        rows = await world.list_revision_firmware(BENCH, revision.revision_id)

        assert [(row.firmware, row.latest_release, row.versions, row.drafts) for row in rows] == [
            (greenhouse, None, 0, 0),
            (weather, release, 2, 1),
        ]
        assert world.work.commits == 0

    async def test_a_revision_running_nothing_runs_no_firmware(self) -> None:
        world = World()
        world.hold_firmware("Weather station")
        revision = world.directory.hold()

        assert await world.list_revision_firmware(BENCH, revision.revision_id) == []

    async def test_a_revision_the_workspace_doesnt_hold_is_not_found(self) -> None:
        # Requirement 3.7, even for one firmware still links to after it went (decision 3).
        world = World()
        firmware = world.hold_firmware("Weather station")
        lost = world.directory.hold()
        world.hold_link(firmware, lost.revision_id)
        del world.directory.held[lost.revision_id]

        with pytest.raises(RevisionNotFoundError, match="that revision doesn't exist"):
            await world.list_revision_firmware(BENCH, lost.revision_id)
