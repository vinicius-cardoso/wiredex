"""The sample firmware a demo bench holds, and putting it back (ADR 0007, decision 15).

A guest may create, edit, release and delete whatever they like in their own bench, so
restoring is not a merge: the workspace's firmware is cleared and the samples written again,
which is what makes a demo bench look the same every morning (requirement 10.4).

The samples go in through `CreateFirmware`, `LinkRevision`, `StartVersion`, `AddSourceFiles`,
`UpdateSourceFile`, `UpdateVersion` and `ReleaseVersion`, the use cases the web calls
(requirement 10.2), so a rule that stopped accepting a sample would fail the nightly job rather
than seed something the app can't hold. A firmware's first version is written from nothing,
and every later one starts from the version before it, as *New version from this* does, and
edits only the files that changed, so a release reads as what it changed.

Firmware runs last in a reset, after projects, because the samples run on the sample revisions
(requirement 10.1). A sample names a revision by its project's name and its label, and the
composition root resolves those names to the ids the projects' restore just minted and hands
them here through `DemoRevisions`, so firmware reads no other module. The weather station's `B`
is forked from `A` before this restore links anything to that `A`, so the fork copies no link,
and `B` is linked here as `A` is.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from wiredex.firmware.application.demo_sources import (
    GREENHOUSE_INO,
    PICO_BLINK_MAIN_1_0,
    PICO_BLINK_MAIN_1_1,
    WEATHER_STATION_CONFIG_H,
    WEATHER_STATION_INO_1_0,
    WEATHER_STATION_INO_1_1,
    WEATHER_STATION_INO_1_2,
)
from wiredex.firmware.application.firmware import CreateFirmware, UnitOfWorkFactory
from wiredex.firmware.application.links import LinkRevision
from wiredex.firmware.application.ports import NewSourceFile
from wiredex.firmware.application.sources import AddSourceFiles, UpdateSourceFile
from wiredex.firmware.application.versions import ReleaseVersion, StartVersion, UpdateVersion
from wiredex.firmware.domain.firmware import FirmwareDetails
from wiredex.firmware.domain.semver import SemVer
from wiredex.firmware.domain.source import SourceFiles
from wiredex.firmware.domain.values import (
    BoardTarget,
    Changelog,
    Description,
    FirmwareId,
    FirmwareName,
    Framework,
    RevisionId,
    VersionId,
    WorkspaceId,
)


@dataclass(frozen=True, slots=True)
class RevisionName:
    """A sample revision as the sample projects name it: its project's name and its label,
    which stay the same from one reset to the next while its id doesn't."""

    project: str
    label: str


# The bench's revisions by name, resolved by the composition root once the projects' restore
# has minted their ids. A revision the sample projects no longer hold is simply absent, and its
# link is skipped: the seeding never links a revision that isn't there.
type DemoRevisions = Callable[[WorkspaceId], Awaitable[Mapping[RevisionName, RevisionId]]]


@dataclass(frozen=True, slots=True)
class SampleFile:
    """A source file as the editor's path and text boxes would hold it."""

    path: str
    text: str


@dataclass(frozen=True, slots=True)
class SampleVersion:
    """A version as its owner wrote it: its number, its changelog and every file it holds.

    Every sample version has a changelog, the draft's included, so any of them could be
    released. A version after its firmware's first starts from the one before it, whose files
    it copies, so a sample version keeps every path its base holds: the restore edits the
    copies whose text changed and adds the files that are new.
    """

    number: str
    changelog: str
    files: tuple[SampleFile, ...]
    released: bool = True


@dataclass(frozen=True, slots=True)
class SampleFirmware:
    """A sample firmware: its details, the sample revisions it runs on in the order they are
    linked, and its versions, lowest first, each started from the one before."""

    name: str
    target: str
    framework: Framework
    description: str
    runs_on: tuple[RevisionName, ...]
    versions: tuple[SampleVersion, ...]


# Small on purpose, and still enough to show what firmware does (decision 15): a firmware on
# two revisions, with two releases and a draft above them; one on a single revision with one
# release; and one on no revision, for the sample Pico, whose two releases let the flash log
# show a board one release behind. The sources use the pins the sample netlists wire
# (requirement 10.3).
SAMPLE_FIRMWARE: tuple[SampleFirmware, ...] = (
    SampleFirmware(
        name="Weather station",
        target="esp32:esp32:esp32",
        framework=Framework.ARDUINO,
        description=(
            "The weather station's sketch: temperature, humidity and pressure from the "
            "BME280, every five minutes, over serial."
        ),
        runs_on=(RevisionName("Weather station", "A"), RevisionName("Weather station", "B")),
        versions=(
            SampleVersion(
                "1.0.0",
                changelog=(
                    "First release: reads the BME280 at 0x76 every five minutes and prints the "
                    "temperature, humidity and pressure over serial."
                ),
                files=(SampleFile("weather_station.ino", WEATHER_STATION_INO_1_0),),
            ),
            SampleVersion(
                "1.1.0",
                changelog=(
                    "Sleeps between readings, the ESP32 in deep sleep and the BME280 in forced "
                    "mode, so the station can run on a battery.\n"
                    "\n"
                    "The pins, the sensor's address and the interval move into config.h."
                ),
                files=(
                    SampleFile("weather_station.ino", WEATHER_STATION_INO_1_1),
                    SampleFile("config.h", WEATHER_STATION_CONFIG_H),
                ),
            ),
            SampleVersion(
                "1.2.0",
                changelog=(
                    "Each reading is the average of three measurements, which smooths out the "
                    "sensor's noise."
                ),
                files=(
                    SampleFile("weather_station.ino", WEATHER_STATION_INO_1_2),
                    SampleFile("config.h", WEATHER_STATION_CONFIG_H),
                ),
                released=False,
            ),
        ),
    ),
    SampleFirmware(
        name="Greenhouse controller",
        target="esp32:esp32:esp32",
        framework=Framework.ARDUINO,
        description=(
            "Waters the tomatoes: runs the pump from when the soil reads dry until it reads "
            "wet again."
        ),
        runs_on=(RevisionName("Greenhouse controller", "A"),),
        versions=(
            SampleVersion(
                "0.1.0",
                changelog=(
                    "First release: reads the soil probe on GPIO34 every second and runs the "
                    "pump on GPIO26 from when the soil reads dry until it reads wet again."
                ),
                files=(SampleFile("greenhouse.ino", GREENHOUSE_INO),),
            ),
        ),
    ),
    SampleFirmware(
        name="Pico blink",
        target="RPI_PICO",
        framework=Framework.MICROPYTHON,
        description=(
            "Blinks the Pico's on-board LED: the smallest program that shows a board took its "
            "firmware."
        ),
        runs_on=(),
        versions=(
            SampleVersion(
                "1.0.0",
                changelog="First release: the on-board LED blinks once a second.",
                files=(SampleFile("main.py", PICO_BLINK_MAIN_1_0),),
            ),
            SampleVersion(
                "1.1.0",
                changelog="The LED fades in and out with PWM instead of blinking.",
                files=(SampleFile("main.py", PICO_BLINK_MAIN_1_1),),
            ),
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class SampleFirmwareWrites:
    """The seven use cases the samples are written through, bundled into one argument.

    `RestoreSampleFirmware` also needs a unit of work for the clear and the sample revisions,
    and nine constructor arguments break ruff's `max-args = 5`, which nothing in the codebase
    suppresses (as projects' `SampleWrites` found). These belong together anyway: a firmware,
    its links, and its versions with their files, all written as the web writes them.
    """

    create_firmware: CreateFirmware
    link_revision: LinkRevision
    start_version: StartVersion
    add_source_files: AddSourceFiles
    update_source_file: UpdateSourceFile
    update_version: UpdateVersion
    release_version: ReleaseVersion


class RestoreSampleFirmware:
    """Puts one demo bench's sample firmware back, whatever the guest did to it.

    Part of the nightly `wiredex demo reset` and of `wiredex demo invite` (ADR 0011, decision
    15), after the sample projects. Which workspaces are demo benches is identity's to answer,
    and which ids the sample revisions have is projects', so the composition root asks there and
    hands the answers here: firmware imports no other module.
    """

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        writes: SampleFirmwareWrites,
        demo_revisions: DemoRevisions,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._writes = writes
        self._demo_revisions = demo_revisions

    async def __call__(self, workspace_id: WorkspaceId) -> int:
        """Restores the bench's sample firmware and returns how many it ended with.

        The clear is one transaction; each firmware, link, version, batch of files, edit,
        changelog and release then goes in through its own use case, each its own transaction,
        as the web writes them. The workspace it is opened for is the only one any step can
        touch (ADR 0007).
        """
        await self._clear(workspace_id)
        revisions = await self._demo_revisions(workspace_id)
        for sample in SAMPLE_FIRMWARE:
            await self._write(workspace_id, sample, revisions)
        return len(SAMPLE_FIRMWARE)

    async def _clear(self, workspace_id: WorkspaceId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            await work.clear()
            await work.commit()

    async def _write(
        self,
        workspace_id: WorkspaceId,
        sample: SampleFirmware,
        revisions: Mapping[RevisionName, RevisionId],
    ) -> None:
        details = FirmwareDetails(
            FirmwareName(sample.name),
            BoardTarget(sample.target),
            sample.framework,
            Description(sample.description),
        )
        view = await self._writes.create_firmware(workspace_id, details)
        firmware_id = view.firmware.id
        # Linked in the order the sample names them, which is the order its page lists them
        # (requirement 3.5).
        for name in sample.runs_on:
            revision_id = revisions.get(name)
            if revision_id is not None:
                await self._writes.link_revision(workspace_id, firmware_id, revision_id)
        base: VersionId | None = None
        for version in sample.versions:
            base = await self._write_version(workspace_id, firmware_id, version, base)

    async def _write_version(
        self,
        workspace_id: WorkspaceId,
        firmware_id: FirmwareId,
        sample: SampleVersion,
        base: VersionId | None,
    ) -> VersionId:
        """A version started from `base`, the one before it, then its files, its changelog and,
        unless it is the draft, its release, which comes last because it freezes the rest."""
        number = SemVer.parse(sample.number)
        view = await self._writes.start_version(workspace_id, firmware_id, number, base)
        version_id = view.version.id
        await self._write_files(workspace_id, version_id, view.files, sample.files)
        await self._writes.update_version(
            workspace_id, version_id, number, Changelog(sample.changelog)
        )
        if sample.released:
            await self._writes.release_version(workspace_id, version_id)
        return version_id

    async def _write_files(
        self,
        workspace_id: WorkspaceId,
        version_id: VersionId,
        copies: SourceFiles,
        files: Sequence[SampleFile],
    ) -> None:
        """The version's files over the copies its base gave it: a copy whose text changed is
        edited under its id, as the editor's *Edit* writes it, a copy that didn't is left as
        it is, and the new files are added in one batch, as files chosen together are."""
        held = {str(copy.path): copy for copy in copies.items}
        new: list[NewSourceFile] = []
        for file in files:
            copy = held.get(file.path)
            if copy is None:
                new.append(NewSourceFile(file.path, file.text))
            elif str(copy.text) != file.text:
                edit = NewSourceFile(file.path, file.text)
                await self._writes.update_source_file(workspace_id, version_id, copy.id, edit)
        if new:
            await self._writes.add_source_files(workspace_id, version_id, new)
