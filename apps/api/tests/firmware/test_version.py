import re
from dataclasses import astuple, dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.firmware.domain.errors import (
    FirmwareField,
    FirmwareRefusal,
    InvalidVersionError,
    NoChangelogError,
    NoFilesError,
    VersionNotFoundError,
    VersionReleasedError,
    VersionTakenError,
)
from wiredex.firmware.domain.firmware import Firmware, FirmwareDetails
from wiredex.firmware.domain.semver import MAX_VERSION_LENGTH, Identifier, SemVer
from wiredex.firmware.domain.source import SourceFile, SourceFiles, SourcePath, SourceText
from wiredex.firmware.domain.values import (
    BoardTarget,
    Changelog,
    Description,
    FirmwareId,
    FirmwareName,
    Framework,
    SourceFileId,
    VersionId,
    WorkspaceId,
)
from wiredex.firmware.domain.version import FirmwareVersion, FirmwareVersions, VersionStatus

NOW = datetime(2026, 9, 30, 3, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
LATEST = NOW + timedelta(days=1)
BENCH = WorkspaceId(uuid7())

WEATHER_STATION = FirmwareDetails(
    FirmwareName("Weather station"),
    BoardTarget("esp32:esp32:esp32"),
    Framework.ARDUINO,
    Description("Reads the BME280 at 0x76 on GPIO21 and GPIO22 every five minutes."),
)
AVERAGES = Changelog("Averages three readings.")
SLEEPS = Changelog("Sleeps between readings.\n\n- config.h holds the pins and the interval.")
SKETCH = SourceFiles.of(
    [
        SourceFile(
            SourceFileId(uuid7()),
            SourcePath("weather_station.ino"),
            SourceText("void setup() {}\nvoid loop() {}\n"),
        )
    ]
)


def a_firmware(details: FirmwareDetails = WEATHER_STATION) -> Firmware:
    return Firmware.start(FirmwareId(uuid7()), BENCH, details, NOW)


def a_draft(
    firmware: Firmware, number: str = "1.2.0", base: FirmwareVersion | None = None
) -> FirmwareVersion:
    return FirmwareVersion.draft(VersionId(uuid7()), firmware, SemVer.parse(number), base, NOW)


def a_release(firmware: Firmware, number: str = "1.1.0", at: datetime = LATER) -> FirmwareVersion:
    """A version drafted, given a changelog and released: the only way the domain makes one."""
    version = a_draft(firmware, number)
    version.revise(version.number, SLEEPS, NOW)
    version.release(SKETCH, at)
    return version


def _numbers(versions: FirmwareVersions) -> list[str]:
    return [str(version.number) for version in versions.items]


class TestFirmware:
    def test_a_new_firmware_is_created_and_changed_at_the_same_instant(self) -> None:
        firmware = a_firmware()

        assert firmware.workspace_id == BENCH
        assert firmware.details == WEATHER_STATION
        assert firmware.created_at == firmware.updated_at == NOW

    def test_a_firmware_needs_no_description(self) -> None:
        pico = FirmwareDetails(
            FirmwareName("Pico blink"), BoardTarget("RPI_PICO"), Framework.MICROPYTHON
        )

        assert a_firmware(pico).description is None

    def test_revising_replaces_the_details_whole_and_stamps_when(self) -> None:
        firmware = a_firmware()
        edited = FirmwareDetails(
            FirmwareName("Weather station S3"),
            BoardTarget("esp32:esp32:esp32s3"),
            Framework.PLATFORMIO,
        )

        assert firmware.revise(edited, LATER)
        assert firmware.details == edited
        # The details are replaced whole, so the description left out is cleared.
        assert firmware.description is None
        assert firmware.created_at == NOW
        assert firmware.updated_at == LATER

    def test_revising_with_the_same_details_changes_nothing_and_keeps_the_stamp(self) -> None:
        # Requirement 1.7: the use case skips the commit on False, and a firmware whose date
        # moved would climb the list for an edit that did nothing.
        firmware = a_firmware()
        same = FirmwareDetails(
            FirmwareName(" Weather  station "),
            BoardTarget("esp32:esp32:esp32\n"),
            Framework("arduino"),
            Description("Reads the BME280 at 0x76 on GPIO21 and GPIO22 every five minutes.\r\n"),
        )

        assert not firmware.revise(same, LATER)
        assert firmware.updated_at == NOW

    def test_a_name_in_another_case_is_an_edit(self) -> None:
        # A name keeps the case it is typed in; only its uniqueness ignores case.
        firmware = a_firmware()
        renamed = replace(WEATHER_STATION, name=FirmwareName("Weather Station"))

        assert firmware.revise(renamed, LATER)
        assert str(firmware.name) == "Weather Station"

    def test_touching_moves_only_its_last_change(self) -> None:
        firmware = a_firmware()

        firmware.touch(LATER)

        assert firmware.updated_at == LATER
        assert firmware.created_at == NOW
        assert firmware.details == WEATHER_STATION


class TestDraft:
    def test_takes_its_firmwares_workspace_and_id(self) -> None:
        firmware = a_firmware()

        version = FirmwareVersion.draft(VersionId(uuid7()), firmware, SemVer(0, 1, 0), None, NOW)

        assert version.workspace_id == firmware.workspace_id
        assert version.firmware_id == firmware.id
        assert version.number == SemVer(0, 1, 0)
        assert version.status is VersionStatus.DRAFT
        assert version.changelog is None
        assert version.based_on is None
        assert version.created_at == version.updated_at == NOW
        assert version.released_at is None

    @pytest.mark.parametrize("released", [False, True])
    def test_records_the_version_it_started_from_draft_or_released(self, released: bool) -> None:
        firmware = a_firmware()
        base = a_release(firmware) if released else a_draft(firmware, "1.1.0")

        version = a_draft(firmware, "1.2.0", base)

        assert version.based_on == base.id
        assert version.status is VersionStatus.DRAFT
        # A changelog says what this version changed, so the base's isn't carried.
        assert version.changelog is None

    def test_a_version_of_another_firmware_is_no_base(self) -> None:
        # Requirement 5.9: a 404, as a version the workspace doesn't hold is.
        elsewhere = a_draft(a_firmware(), "1.0.0")

        with pytest.raises(VersionNotFoundError, match="isn't one of this firmware's"):
            a_draft(a_firmware(), "1.1.0", elsewhere)


class TestEditing:
    def test_replaces_a_drafts_number_and_changelog_and_stamps_when(self) -> None:
        version = a_draft(a_firmware(), "1.2.0")

        assert version.revise(SemVer.parse("1.3.0-rc.1"), AVERAGES, LATER)
        assert (version.number, version.changelog) == (SemVer(1, 3, 0, ("rc", 1)), AVERAGES)
        assert version.created_at == NOW
        assert version.updated_at == LATER

    def test_an_edit_that_changes_nothing_answers_false_and_keeps_the_stamp(self) -> None:
        # Requirement 5.7: the same number and changelog, typed another way.
        version = a_draft(a_firmware(), "1.2.0")
        version.revise(version.number, AVERAGES, NOW)

        unchanged = Changelog("Averages three readings.\r\n")
        assert not version.revise(SemVer.parse(" v1.2.0 "), unchanged, LATER)
        assert version.updated_at == NOW

    def test_clearing_the_changelog_is_an_edit(self) -> None:
        version = a_draft(a_firmware(), "1.2.0")
        version.revise(version.number, AVERAGES, NOW)

        assert version.revise(version.number, None, LATER)
        assert version.changelog is None

    def test_touching_moves_only_its_last_change(self) -> None:
        # One of its files changed.
        version = a_draft(a_firmware(), "1.2.0")

        version.touch(LATER)

        assert version.updated_at == LATER
        assert (version.number, version.changelog, version.status, version.created_at) == (
            SemVer(1, 2, 0),
            None,
            VersionStatus.DRAFT,
            NOW,
        )

    def test_a_released_version_is_refused_even_unchanged(self) -> None:
        # Requirement 6.4: property 7 below covers every other write.
        version = a_release(a_firmware(), "1.1.0")

        with pytest.raises(VersionReleasedError, match=re.escape("1.1.0 is released")) as refused:
            version.revise(version.number, version.changelog, LATEST)
        assert refused.value.code is FirmwareRefusal.VERSION_RELEASED
        assert version.updated_at == LATER


class TestRelease:
    def test_marks_a_draft_released_and_records_when(self) -> None:
        version = a_draft(a_firmware(), "1.1.0")
        version.revise(version.number, SLEEPS, NOW)

        version.release(SKETCH, LATER)

        assert version.status is VersionStatus.RELEASED
        assert version.released_at == version.updated_at == LATER

    def test_a_draft_with_no_file_is_refused_and_left_a_draft(self) -> None:
        version = a_draft(a_firmware(), "1.1.0")
        version.revise(version.number, SLEEPS, NOW)

        with pytest.raises(NoFilesError, match=re.escape("1.1.0 has no source file to release")):
            version.release(SourceFiles(), LATER)
        assert (version.status, version.released_at, version.updated_at) == (
            VersionStatus.DRAFT,
            None,
            NOW,
        )

    def test_a_draft_with_no_changelog_is_refused_on_the_changelog(self) -> None:
        version = a_draft(a_firmware(), "1.1.0")

        with pytest.raises(NoChangelogError, match=re.escape("1.1.0 has no changelog")) as refused:
            version.release(SKETCH, LATER)
        assert refused.value.field is FirmwareField.CHANGELOG
        assert (version.status, version.released_at, version.updated_at) == (
            VersionStatus.DRAFT,
            None,
            NOW,
        )

    def test_a_draft_with_neither_is_refused_for_its_files_first(self) -> None:
        with pytest.raises(NoFilesError):
            a_draft(a_firmware(), "1.1.0").release(SourceFiles(), LATER)

    def test_a_released_version_is_not_released_again(self) -> None:
        # Requirement 6.5: refused before its files or its changelog are looked at.
        version = a_release(a_firmware(), "1.1.0")

        with pytest.raises(VersionReleasedError, match="start a new version from it"):
            version.release(SourceFiles(), LATEST)
        assert version.released_at == LATER

    def test_only_a_draft_is_editable(self) -> None:
        firmware = a_firmware()
        a_draft(firmware, "1.2.0").ensure_editable()

        with pytest.raises(VersionReleasedError, match=re.escape("1.1.0 is released")):
            a_release(firmware, "1.1.0").ensure_editable()


class TestFirmwareVersions:
    def test_lists_the_highest_first_whatever_the_order_given(self) -> None:
        firmware = a_firmware()
        numbers = ["1.2.0-rc.1", "0.1.0", "1.10.0", "1.2.0", "1.9.0"]

        versions = FirmwareVersions.of(a_draft(firmware, number) for number in numbers)

        assert _numbers(versions) == ["1.10.0", "1.9.0", "1.2.0", "1.2.0-rc.1", "0.1.0"]
        assert versions.highest is versions.items[0]

    def test_a_firmware_with_no_version_has_no_highest_and_no_release(self) -> None:
        versions = FirmwareVersions()

        assert FirmwareVersions.of([]) == versions
        assert versions.highest is None
        assert versions.latest_release is None

    def test_the_latest_release_is_the_released_one_of_highest_precedence(self) -> None:
        # 1.2.0 is a draft above it, and 1.0.1, a fix of 1.0.0, was released after it.
        firmware = a_firmware()
        latest = a_release(firmware, "1.1.0")
        versions = FirmwareVersions.of(
            [
                a_release(firmware, "1.0.0"),
                latest,
                a_draft(firmware, "1.2.0"),
                a_release(firmware, "1.0.1", at=LATEST),
            ]
        )

        assert versions.latest_release is latest
        assert versions.highest is not latest

    def test_a_firmware_of_drafts_has_no_release(self) -> None:
        firmware = a_firmware()
        versions = FirmwareVersions.of([a_draft(firmware, "0.1.0"), a_draft(firmware, "0.2.0")])

        assert versions.latest_release is None

    def test_suggests_0_1_0_then_the_successor_of_the_highest(self) -> None:
        firmware = a_firmware()
        versions = FirmwareVersions.of(
            [a_release(firmware, "1.0.0"), a_draft(firmware, "1.2.0"), a_release(firmware, "1.1.0")]
        )

        assert FirmwareVersions().suggested() == SemVer(0, 1, 0)
        # The weather station's 1.2.0 is a draft, and the highest all the same.
        assert versions.suggested() == SemVer(1, 2, 1)

    def test_answers_the_suggestion_when_no_number_is_asked(self) -> None:
        versions = FirmwareVersions.of([a_draft(a_firmware(), "1.3.0-rc.1")])

        assert versions.number_for(None) == SemVer.parse("1.3.0-rc.2")
        assert FirmwareVersions().number_for(None) == SemVer(0, 1, 0)

    def test_accepts_a_number_no_version_holds(self) -> None:
        versions = FirmwareVersions.of([a_draft(a_firmware(), "1.1.0")])

        assert versions.number_for(SemVer.parse("2.0.0")) == SemVer(2, 0, 0)

    @pytest.mark.parametrize(
        ("held", "asked"), [("1.1.0", "v1.1.0"), ("1.3.0-rc.1", " 1.3.0-RC.1")]
    )
    def test_refuses_a_number_another_version_holds(self, held: str, asked: str) -> None:
        # Requirement 5.2: a number is its canonical text, so each pair is one number.
        versions = FirmwareVersions.of([a_draft(a_firmware(), held)])

        with pytest.raises(VersionTakenError) as refused:
            versions.number_for(SemVer.parse(asked))
        assert str(refused.value) == f"this firmware already has a version {held}"
        assert refused.value.field is FirmwareField.VERSION
        assert refused.value.item == held

    def test_a_versions_own_number_doesnt_count_against_it(self) -> None:
        # Requirement 5.7: a draft edited with its own number keeps it.
        firmware = a_firmware()
        own = a_draft(firmware, "1.2.0")
        versions = FirmwareVersions.of([a_release(firmware, "1.1.0"), own])

        assert versions.number_for(SemVer.parse("1.2.0"), renaming=own) == own.number

    def test_a_renumber_to_another_versions_number_is_refused(self) -> None:
        firmware = a_firmware()
        own = a_draft(firmware, "1.2.0")
        versions = FirmwareVersions.of([a_release(firmware, "1.1.0"), own])

        with pytest.raises(VersionTakenError, match=re.escape("already has a version 1.1.0")):
            versions.number_for(SemVer.parse("1.1.0"), renaming=own)

    def test_finds_a_version_by_id(self) -> None:
        firmware = a_firmware()
        version = a_draft(firmware, "1.0.0")
        versions = FirmwareVersions.of([version, a_draft(firmware, "1.1.0")])

        assert versions.get(version.id) is version
        assert versions.get(VersionId(uuid7())) is None


# Numbers SemVer.parse takes whose successor it wouldn't: a word gains ".1", and a number, the
# patch or a pre-release's last, can gain a digit.
_SUCCESSOR_PAST_THE_CAP = [
    "1.0.0-" + "a" * (MAX_VERSION_LENGTH - 6),  # 64 characters, and 66 after
    "1.0.0-" + "a" * (MAX_VERSION_LENGTH - 7),  # 63, and 65 after
    "1.0.0-" + "a" * (MAX_VERSION_LENGTH - 8) + ".9",  # 64, and 65 after: .9 becomes .10
    "1.0." + "9" * (MAX_VERSION_LENGTH - 4),  # 64, and 65 after: the patch gains a digit
]


class TestASuggestionPastTheCap:
    """A suggestion longer than a version number can be is refused only when it would be taken:
    a 422 on the version, asking for a number to be typed."""

    @pytest.mark.parametrize("highest", _SUCCESSOR_PAST_THE_CAP)
    def test_is_refused_asking_for_a_number_to_be_typed(self, highest: str) -> None:
        versions = FirmwareVersions.of([a_draft(a_firmware(), highest)])

        with pytest.raises(InvalidVersionError, match="type a number for this version") as refused:
            versions.number_for(None)
        assert refused.value.field is FirmwareField.VERSION
        assert refused.value.item is None

    @pytest.mark.parametrize("highest", _SUCCESSOR_PAST_THE_CAP)
    def test_is_still_what_the_firmware_suggests_and_typing_it_is_refused(
        self, highest: str
    ) -> None:
        # A firmware's page shows the suggestion (requirement 1.8); parse refuses it as typed.
        suggested = FirmwareVersions.of([a_draft(a_firmware(), highest)]).suggested()

        assert suggested == SemVer.parse(highest).successor()
        assert len(str(suggested)) > MAX_VERSION_LENGTH
        with pytest.raises(InvalidVersionError, match="at most 64 characters"):
            SemVer.parse(str(suggested))

    def test_a_suggestion_of_64_characters_is_taken(self) -> None:
        highest = "1.0.0-" + "a" * (MAX_VERSION_LENGTH - 8)  # 62 characters, and 64 after

        suggested = FirmwareVersions.of([a_draft(a_firmware(), highest)]).number_for(None)

        assert len(str(suggested)) == MAX_VERSION_LENGTH
        assert SemVer.parse(str(suggested)) == suggested

    def test_a_typed_number_is_taken_all_the_same(self) -> None:
        versions = FirmwareVersions.of([a_draft(a_firmware(), _SUCCESSOR_PAST_THE_CAP[0])])

        assert versions.number_for(SemVer.parse("1.0.1")) == SemVer(1, 0, 1)


# --- Property 7: a released version never changes -------------------------------------------

# Small pools, so an edit often asks for the version's own number or changelog again.
_IDENTIFIERS: st.SearchStrategy[Identifier] = st.integers(0, 2) | st.sampled_from(["rc", "beta"])
_NUMBERS = st.builds(
    SemVer,
    st.integers(0, 2),
    st.integers(0, 2),
    st.integers(0, 2),
    st.lists(_IDENTIFIERS, max_size=2).map(tuple),
)
_CHANGELOGS = st.sampled_from([AVERAGES, SLEEPS, Changelog("Fades the LED in and out.")])
# Paths that clash in case, so an added batch would be refused for its paths too, were the
# version still a draft.
_PATHS = st.sampled_from(
    ["weather_station.ino", "config.h", "Config.h", "lib/bme.h", "main.py"]
).map(SourcePath)
_TEXTS = st.sampled_from(["", "#define SDA 21\n", "void loop() {}\r\n", "\tpin = 26  "]).map(
    SourceText
)
_FILES = st.builds(SourceFile, st.uuids().map(SourceFileId), _PATHS, _TEXTS)


def _versions_files(min_size: int) -> st.SearchStrategy[SourceFiles]:
    files = st.lists(_FILES, min_size=min_size, max_size=3, unique_by=lambda file: file.path.fold())
    return files.map(SourceFiles.of)


@dataclass(frozen=True)
class _Edit:
    number: SemVer
    changelog: Changelog | None

    def apply(self, version: FirmwareVersion, files: SourceFiles) -> SourceFiles:
        version.revise(self.number, self.changelog, LATEST)
        return files


@dataclass(frozen=True)
class _ReleaseAgain:
    files: SourceFiles

    def apply(self, version: FirmwareVersion, files: SourceFiles) -> SourceFiles:
        version.release(self.files, LATEST)
        return files


# A file written as the use cases write one: the version asked first, then its files changed.


@dataclass(frozen=True)
class _AddFiles:
    new: tuple[SourceFile, ...]

    def apply(self, version: FirmwareVersion, files: SourceFiles) -> SourceFiles:
        version.ensure_editable()
        return files.adding(self.new)


@dataclass(frozen=True)
class _EditFile:
    which: int
    path: SourcePath
    text: SourceText

    def apply(self, version: FirmwareVersion, files: SourceFiles) -> SourceFiles:
        version.ensure_editable()
        held = files.items[self.which % len(files.items)]
        return files.replacing(SourceFile(held.id, self.path, self.text))


@dataclass(frozen=True)
class _RemoveFile:
    which: int

    def apply(self, version: FirmwareVersion, files: SourceFiles) -> SourceFiles:
        version.ensure_editable()
        return files.without(files.items[self.which % len(files.items)].id)


type _Write = _Edit | _ReleaseAgain | _AddFiles | _EditFile | _RemoveFile


@st.composite
def _released(draw: st.DrawFn) -> tuple[FirmwareVersion, SourceFiles]:
    """A version drafted with one number, edited to another with a changelog, then released
    with its files: the only way the domain makes a release."""
    version = FirmwareVersion.draft(VersionId(uuid7()), a_firmware(), draw(_NUMBERS), None, NOW)
    version.revise(draw(_NUMBERS), draw(_CHANGELOGS), NOW)
    files = draw(_versions_files(min_size=1))
    version.release(files, LATER)
    return version, files


def _writes(version: FirmwareVersion) -> st.SearchStrategy[_Write]:
    """Every write to a version's number, changelog or files: edits to its own number and
    changelog among them, a second release with any files or none, and batches that would
    clash."""
    numbers = st.just(version.number) | _NUMBERS
    changelogs = st.just(version.changelog) | st.none() | _CHANGELOGS
    return (
        st.builds(_Edit, numbers, changelogs)
        | st.builds(_ReleaseAgain, _versions_files(min_size=0))
        | st.builds(_AddFiles, st.lists(_FILES, min_size=1, max_size=3).map(tuple))
        | st.builds(_EditFile, st.integers(0, 2), _PATHS, _TEXTS)
        | st.builds(_RemoveFile, st.integers(0, 2))
    )


@given(data=st.data())
def test_a_released_version_never_changes(data: st.DataObject) -> None:
    """Property 7: a released version never changes.

    For any released version and any sequence of number, changelog and file writes after its
    release, every write is refused with version_released, and the number, changelog and files
    are what they were when it was released. The version is drafted, edited and released
    through the entity; the writes edit its number and changelog, its own among them, release
    it again with any files or none, and add, edit or remove files as the use cases will,
    asking ensure_editable first. Nothing else about it changes either: its status, its dates
    and its base.

    **Validates: Requirements 6.4, 6.5**
    """
    version, files = data.draw(_released())
    released, kept = astuple(version), files
    for write in data.draw(st.lists(_writes(version), min_size=1, max_size=6)):
        with pytest.raises(VersionReleasedError) as refused:
            files = write.apply(version, files)
        assert refused.value.code is FirmwareRefusal.VERSION_RELEASED
        assert astuple(version) == released
    assert files == kept


class TestNewerThan:
    def test_answers_the_latest_release_above_the_number(self) -> None:
        firmware = a_firmware()
        latest = a_release(firmware, "1.1.0")
        versions = FirmwareVersions.of(
            [a_release(firmware, "1.0.0"), latest, a_draft(firmware, "1.2.0")]
        )

        assert versions.newer_than(SemVer(1, 0, 0)) is latest
        # The board runs the latest release, and the draft above it isn't code to flash yet.
        assert versions.newer_than(SemVer(1, 1, 0)) is None
        assert versions.newer_than(SemVer(1, 2, 0)) is None

    def test_a_released_pre_release_counts(self) -> None:
        # The owner released it (15's decision 10).
        firmware = a_firmware()
        candidate = a_release(firmware, "1.1.0-rc.1")
        versions = FirmwareVersions.of([a_release(firmware, "1.0.0"), candidate])

        assert versions.newer_than(SemVer(1, 0, 0)) is candidate

    def test_a_firmware_never_released_has_nothing_newer(self) -> None:
        versions = FirmwareVersions.of([a_draft(a_firmware(), "0.2.0")])

        assert versions.newer_than(SemVer(0, 1, 0)) is None
        assert FirmwareVersions().newer_than(SemVer(0, 1, 0)) is None


# --- Property 4: the newer release is the highest release above ------------------------------


@st.composite
def _a_firmwares_versions(draw: st.DrawFn) -> list[FirmwareVersion]:
    """Versions of one firmware with distinct numbers, each a draft or released."""
    firmware = a_firmware()
    versions = []
    for number in draw(st.lists(_NUMBERS, max_size=5, unique=True)):
        version = FirmwareVersion.draft(VersionId(uuid7()), firmware, number, None, NOW)
        if draw(st.booleans()):
            version.revise(number, SLEEPS, NOW)
            version.release(SKETCH, LATER)
        versions.append(version)
    return versions


@given(versions=_a_firmwares_versions(), number=_NUMBERS)
def test_the_newer_release_is_the_highest_release_above(
    versions: list[FirmwareVersion], number: SemVer
) -> None:
    """Property 4: the newer release is the highest release above.

    For any versions of a firmware and any number, newer_than answers the highest released
    version when it is above the number, and none otherwise. A draft above every release
    never counts, and the number is often one of the firmware's own, released or not.

    **Validates: Requirements 2.3**
    """
    released = [version for version in versions if version.status is VersionStatus.RELEASED]
    highest = max(released, key=lambda version: version.number, default=None)
    expected = highest if highest is not None and number < highest.number else None

    assert FirmwareVersions.of(versions).newer_than(number) is expected
