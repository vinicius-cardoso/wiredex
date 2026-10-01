"""Restoring a demo bench's sample firmware, over the in-memory firmware.

The samples go through the use cases the web calls (requirement 10.2), so these tests read what
those wrote: the three firmware with their details, the revisions they run on, and their
versions with their changelogs, bases and files (10.1); the sources wired as the sample
netlists are (10.3); and the same bench again after a second restore, whatever a guest did in
between (10.4).

The fake directory holds the revisions the sample projects write, under the names they give
them, as the projects' restore leaves a bench just before the firmware's restore runs.
"""

from collections.abc import Mapping
from itertools import pairwise

import pytest

from support.firmware import BENCH, World
from wiredex.catalog.application.demo import DEVKITC_PINS
from wiredex.firmware.application.demo import (
    SAMPLE_FIRMWARE,
    RestoreSampleFirmware,
    RevisionName,
    SampleFirmwareWrites,
)
from wiredex.firmware.application.ports import FirmwareView
from wiredex.firmware.domain.firmware import Firmware, FirmwareDetails
from wiredex.firmware.domain.semver import SemVer
from wiredex.firmware.domain.values import (
    BoardTarget,
    FirmwareName,
    Framework,
    RevisionId,
    SourceFileId,
    WorkspaceId,
)
from wiredex.firmware.domain.version import FirmwareVersion, VersionStatus
from wiredex.projects.application.demo import SAMPLE_PROJECTS

pytestmark = pytest.mark.anyio

WEATHER_STATION, GREENHOUSE, PICO_BLINK = "Weather station", "Greenhouse controller", "Pico blink"


def _sample_revisions() -> list[tuple[str, str, str]]:
    """The revisions the projects' restore writes, each sample project's first and its forks:
    their project's name, their label and their summary."""
    revisions: list[tuple[str, str, str]] = []
    for project in SAMPLE_PROJECTS:
        revisions.append((project.name, project.first.label, project.first.summary))
        revisions += [(project.name, fork.label, fork.summary) for fork in project.forks]
    return revisions


class Demo:
    """An empty firmware bench beside the sample revisions, and the restore over them."""

    def __init__(self, missing: tuple[RevisionName, ...] = ()) -> None:
        self.world = World()
        for project, label, summary in _sample_revisions():
            if RevisionName(project, label) not in missing:
                self.world.directory.hold(project, label, summary)
        world = self.world
        self._restore = RestoreSampleFirmware(
            world.work.for_workspace,
            SampleFirmwareWrites(
                create_firmware=world.create_firmware,
                link_revision=world.link_revision,
                start_version=world.start_version,
                add_source_files=world.add_source_files,
                update_source_file=world.update_source_file,
                update_version=world.update_version,
                release_version=world.release_version,
            ),
            self.sample_revisions,
        )

    async def restore(self, workspace_id: WorkspaceId) -> int:
        return await self._restore(workspace_id)

    async def sample_revisions(
        self, workspace_id: WorkspaceId
    ) -> Mapping[RevisionName, RevisionId]:
        """What the composition root reads from projects: the bench's revisions by name."""
        assert workspace_id == BENCH
        return {
            RevisionName(facts.project_name, facts.label): facts.revision_id
            for facts in self.world.directory.held.values()
        }

    def firmware(self) -> dict[str, Firmware]:
        return {str(one.name): one for one in self.world.work.firmwares.saved.values()}

    def versions(self, name: str) -> dict[str, FirmwareVersion]:
        firmware = self.firmware()[name]
        saved = self.world.work.versions.saved.values()
        return {str(one.number): one for one in saved if one.firmware_id == firmware.id}

    def files(self, name: str, number: str) -> dict[str, str]:
        """A version's files by path, each one's text."""
        version = self.versions(name)[number]
        return {str(file.path): str(file.text) for file in self.world.work.sources.of(version.id)}

    def file_ids(self, name: str, number: str) -> set[SourceFileId]:
        version = self.versions(name)[number]
        return {file.id for file in self.world.work.sources.of(version.id)}

    async def page(self, name: str) -> FirmwareView:
        return await self.world.get_firmware(BENCH, self.firmware()[name].id)

    def snapshot(self) -> dict[str, tuple[object, ...]]:
        """The bench as a guest reads it, without the ids and dates a restore mints anew."""
        held = self.world.directory.held
        links = self.world.work.links.saved
        rows: dict[str, tuple[object, ...]] = {}
        for name, firmware in self.firmware().items():
            versions = self.versions(name)
            numbers = {version.id: number for number, version in versions.items()}
            rows[name] = (
                str(firmware.target),
                firmware.framework,
                str(firmware.description),
                sorted(
                    (held[revision_id].project_name, held[revision_id].label)
                    for firmware_id, revision_id in links
                    if firmware_id == firmware.id
                ),
                {
                    number: (
                        version.status,
                        str(version.changelog),
                        None if version.based_on is None else numbers[version.based_on],
                        self.files(name, number),
                    )
                    for number, version in versions.items()
                },
            )
        return rows


@pytest.fixture
def demo() -> Demo:
    return Demo()


def _lineage(view: FirmwareView) -> list[tuple[str, VersionStatus, str | None]]:
    """A firmware's versions as its page lists them, highest first: each one's number, status
    and the number of the version it was started from."""
    numbers = {summary.version.id: str(summary.version.number) for summary in view.versions}
    return [
        (
            str(summary.version.number),
            summary.version.status,
            None if summary.version.based_on is None else numbers[summary.version.based_on],
        )
        for summary in view.versions
    ]


async def test_a_restore_writes_the_three_sample_firmware(demo: Demo) -> None:
    restored = await demo.restore(BENCH)

    firmware = demo.firmware()
    assert restored == len(firmware) == 3
    assert {name: (str(one.target), one.framework) for name, one in firmware.items()} == {
        WEATHER_STATION: ("esp32:esp32:esp32", Framework.ARDUINO),
        GREENHOUSE: ("esp32:esp32:esp32", Framework.ARDUINO),
        PICO_BLINK: ("RPI_PICO", Framework.MICROPYTHON),
    }
    assert str(firmware[WEATHER_STATION].description).startswith("The weather station's sketch")
    assert all(one.description is not None for one in firmware.values())


async def test_the_samples_run_on_the_sample_revisions(demo: Demo) -> None:
    # Requirement 10.1: the weather station on its A and on B, forked from A before any
    # firmware existed, in the order they were linked; the greenhouse on its A; the Pico on
    # none.
    await demo.restore(BENCH)

    runs_on = {
        name: [(facts.project_name, facts.label) for facts in (await demo.page(name)).runs_on]
        for name in (WEATHER_STATION, GREENHOUSE, PICO_BLINK)
    }
    assert runs_on == {
        WEATHER_STATION: [(WEATHER_STATION, "A"), (WEATHER_STATION, "B")],
        GREENHOUSE: [(GREENHOUSE, "A")],
        PICO_BLINK: [],
    }


async def test_each_version_starts_from_the_one_before_and_the_weather_stations_last_is_a_draft(
    demo: Demo,
) -> None:
    await demo.restore(BENCH)

    station = await demo.page(WEATHER_STATION)
    assert _lineage(station) == [
        ("1.2.0", VersionStatus.DRAFT, "1.1.0"),
        ("1.1.0", VersionStatus.RELEASED, "1.0.0"),
        ("1.0.0", VersionStatus.RELEASED, None),
    ]
    # The draft above them doesn't hide the latest release.
    assert station.latest_release is not None
    assert str(station.latest_release.number) == "1.1.0"
    assert str(station.suggested) == "1.2.1"
    assert _lineage(await demo.page(GREENHOUSE)) == [("0.1.0", VersionStatus.RELEASED, None)]
    pico = await demo.page(PICO_BLINK)
    assert _lineage(pico) == [
        ("1.1.0", VersionStatus.RELEASED, "1.0.0"),
        ("1.0.0", VersionStatus.RELEASED, None),
    ]
    assert pico.latest_release is not None
    assert str(pico.latest_release.number) == "1.1.0"


async def test_every_sample_version_has_its_changelog_the_drafts_included(demo: Demo) -> None:
    await demo.restore(BENCH)

    for sample in SAMPLE_FIRMWARE:
        versions = demo.versions(sample.name)
        assert {number: str(version.changelog) for number, version in versions.items()} == {
            version.number: version.changelog for version in sample.versions
        }
    released = [v for v in demo.world.work.versions.saved.values() if v.released_at is not None]
    assert len(released) == 5


async def test_the_draft_could_be_released_as_it_stands(demo: Demo) -> None:
    # It has files and a changelog, so the release use case takes it (requirement 6.1).
    await demo.restore(BENCH)
    draft = demo.versions(WEATHER_STATION)["1.2.0"]

    view = await demo.world.release_version(BENCH, draft.id)

    assert view.version.status is VersionStatus.RELEASED


async def test_every_version_holds_its_samples_files(demo: Demo) -> None:
    await demo.restore(BENCH)

    for sample in SAMPLE_FIRMWARE:
        for version in sample.versions:
            expected = {file.path: file.text for file in version.files}
            assert demo.files(sample.name, version.number) == expected


async def test_a_later_version_edits_its_copies_and_adds_what_is_new(demo: Demo) -> None:
    # 1.1.0 started from 1.0.0: its sketch is the copy, edited, and config.h is new. 1.2.0
    # started from 1.1.0 and edited only the sketch, so its config.h is the copy as it was.
    # Each copy is a file of its own version, under an id of its own (requirement 5.5).
    await demo.restore(BENCH)

    first, second, draft = (
        demo.files(WEATHER_STATION, number) for number in ("1.0.0", "1.1.0", "1.2.0")
    )
    assert set(first) == {"weather_station.ino"}
    assert set(second) == set(draft) == {"config.h", "weather_station.ino"}
    assert first["weather_station.ino"] != second["weather_station.ino"]
    assert second["weather_station.ino"] != draft["weather_station.ino"]
    assert second["config.h"] == draft["config.h"]
    released, drafted = (demo.file_ids(WEATHER_STATION, number) for number in ("1.1.0", "1.2.0"))
    assert not released & drafted


def _net_pins(project: str, net: str) -> list[str]:
    """A sample net's pins as the projects' sample netlist types them: `U1.SDA`, `R1.2`."""
    sample = next(one for one in SAMPLE_PROJECTS if one.name == project)
    (pins,) = [one.pins for one in sample.first.nets if one.name == net]
    return [pin.strip() for pin in pins.split(",")]


def _wired_gpio(project: str, net: str) -> int:
    """The ESP32 GPIO a sample net wires the board, U1, to: its pin as the netlist names it,
    by number, label or function, found on the sample DevKitC's pinout."""
    (board,) = [pin.removeprefix("U1.") for pin in _net_pins(project, net) if pin[:3] == "U1."]
    (pin,) = [
        pin for pin in DEVKITC_PINS if board in (pin.number, pin.label, *pin.functions.split())
    ]
    return int(pin.label.removeprefix("GPIO"))


def _declared(source: str, name: str) -> str:
    """What a source sets a constant to: `const int SDA_PIN = 21;` sets SDA_PIN to 21."""
    (value,) = [
        line.removesuffix(";").rpartition(" = ")[2]
        for line in source.splitlines()
        if line.startswith("const ") and f" {name} = " in line
    ]
    return value


async def test_the_sample_sources_use_the_pins_the_sample_netlists_wire(demo: Demo) -> None:
    # Requirement 10.3: the BME280 on the pins the weather station's SDA and SCL nets wire, at
    # the address its SDO's net gives it, in every version; the probe and the pump on the pins
    # the greenhouse's SOIL and PUMP nets wire.
    await demo.restore(BENCH)
    sda, scl = _wired_gpio(WEATHER_STATION, "SDA"), _wired_gpio(WEATHER_STATION, "SCL")
    soil, pump = _wired_gpio(GREENHOUSE, "SOIL"), _wired_gpio(GREENHOUSE, "PUMP")
    assert (sda, scl, soil, pump) == (21, 22, 34, 26)
    # SDO on the ground net puts the BME280 at 0x76; on 3V3 it would answer at 0x77.
    assert "U2.SDO" in _net_pins(WEATHER_STATION, "GND")

    for number in ("1.0.0", "1.1.0", "1.2.0"):
        source = "".join(demo.files(WEATHER_STATION, number).values())
        assert _declared(source, "SDA_PIN") == str(sda)
        assert _declared(source, "SCL_PIN") == str(scl)
        assert _declared(source, "SENSOR_ADDRESS") == "0x76"
    greenhouse = demo.files(GREENHOUSE, "0.1.0")["greenhouse.ino"]
    assert _declared(greenhouse, "SOIL_PIN") == str(soil)
    assert _declared(greenhouse, "PUMP_PIN") == str(pump)


async def test_a_second_restore_gives_the_same_firmware(demo: Demo) -> None:
    await demo.restore(BENCH)
    first = demo.snapshot()

    await demo.restore(BENCH)

    assert demo.snapshot() == first
    work = demo.world.work
    # Three firmware, six versions, eight files and three links, none left from the first.
    assert len(work.firmwares.saved) == 3
    assert len(work.versions.saved) == 6
    assert len(work.sources.saved) == 8
    assert len(work.links.saved) == 3


async def test_a_restore_takes_what_a_guest_added_and_puts_back_what_they_changed(
    demo: Demo,
) -> None:
    # Requirement 10.4: the guest's own firmware goes with its version, file and link; a
    # deleted sample comes back, and so do a renamed one, a released draft and an unlink.
    await demo.restore(BENCH)
    sample = demo.snapshot()
    world = demo.world
    station = await demo.page(WEATHER_STATION)
    breadboard, perfboard = (facts.revision_id for facts in station.runs_on)
    theirs = world.hold_firmware("Their robot arm", target="arduino:avr:uno")
    world.hold_file(world.hold_version(theirs, "0.1.0"), "arm.ino", "void loop() {}\n")
    world.hold_link(theirs, breadboard)
    await world.delete_firmware(BENCH, demo.firmware()[GREENHOUSE].id)
    blink = FirmwareDetails(FirmwareName("Their blink"), BoardTarget("RPI_PICO_W"), Framework.OTHER)
    await world.update_firmware(BENCH, demo.firmware()[PICO_BLINK].id, blink)
    await world.release_version(BENCH, demo.versions(WEATHER_STATION)["1.2.0"].id)
    await world.unlink_revision(BENCH, station.firmware.id, perfboard)
    assert set(demo.firmware()) == {WEATHER_STATION, "Their blink", "Their robot arm"}

    await demo.restore(BENCH)

    assert demo.snapshot() == sample
    assert set(demo.firmware()) == {WEATHER_STATION, GREENHOUSE, PICO_BLINK}
    assert len(world.work.sources.saved) == 8


async def test_a_restore_touches_only_the_bench_it_was_asked_for(demo: Demo) -> None:
    await demo.restore(BENCH)

    assert set(demo.world.work.opened_for) == {BENCH}
    assert all(one.workspace_id == BENCH for one in demo.firmware().values())
    assert all(one.workspace_id == BENCH for one in demo.world.work.versions.saved.values())


async def test_a_revision_the_sample_projects_lack_is_not_linked() -> None:
    demo = Demo(missing=(RevisionName(WEATHER_STATION, "B"),))

    await demo.restore(BENCH)

    runs_on = (await demo.page(WEATHER_STATION)).runs_on
    assert [(facts.project_name, facts.label) for facts in runs_on] == [(WEATHER_STATION, "A")]
    assert len(demo.versions(WEATHER_STATION)) == 3


def test_every_sample_link_names_a_revision_the_sample_projects_write() -> None:
    """The data itself: each revision a sample runs on is a sample project's first revision or
    one of its forks, so a reset links every one."""
    written = {RevisionName(project, label) for project, label, _ in _sample_revisions()}
    linked = {name for sample in SAMPLE_FIRMWARE for name in sample.runs_on}
    assert linked <= written
    assert len(linked) == 3


def test_every_later_sample_version_keeps_its_bases_paths_under_a_higher_number() -> None:
    """The data itself: a version starts from the one before it, whose files it copies, and the
    restore only edits and adds, so each version names every path its base holds; its number is
    above its base's, and the sample's numbers read as the editor would take them."""
    for sample in SAMPLE_FIRMWARE:
        for base, version in pairwise(sample.versions):
            assert {file.path for file in base.files} <= {file.path for file in version.files}
            assert SemVer.parse(base.number) < SemVer.parse(version.number)
        assert [str(SemVer.parse(v.number)) for v in sample.versions] == [
            v.number for v in sample.versions
        ]
