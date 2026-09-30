"""The version use cases over the in-memory firmware fakes: starting a version, editing and
releasing a draft, deleting a version and opening one.

The fakes write straight into their stores and count commits, so a refused change is one that
left the stores as they were and committed nothing.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import astuple, dataclass
from datetime import timedelta
from uuid import uuid7

import anyio
import pytest
from hypothesis import given
from hypothesis import strategies as st

from support.firmware import BENCH, NOW, World
from wiredex.firmware.application.ports import NewSourceFile
from wiredex.firmware.application.versions import lock_version
from wiredex.firmware.domain.errors import (
    FirmwareField,
    FirmwareNotFoundError,
    FirmwareRefusal,
    NoChangelogError,
    NoFilesError,
    VersionNotFoundError,
    VersionReleasedError,
    VersionTakenError,
)
from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.semver import Identifier, SemVer
from wiredex.firmware.domain.source import SourceFiles
from wiredex.firmware.domain.values import (
    Changelog,
    FirmwareId,
    SourceFileId,
    VersionId,
)
from wiredex.firmware.domain.version import FirmwareVersion, VersionStatus

pytestmark = pytest.mark.anyio

LATER = NOW + timedelta(minutes=5)
SKETCH = "void setup() {}\nvoid loop() {}\n"
AVERAGES = Changelog("Averages three readings.")


class TestStart:
    async def test_a_first_version_is_an_empty_draft_numbered_0_1_0(self) -> None:
        # Requirements 5.4 and 5.5, under the firmware's lock, moving it up the list (2.2).
        world = World()
        firmware = world.hold_firmware("Weather station")
        world.clock.advance(timedelta(minutes=5))

        view = await world.start_version(BENCH, firmware.id)

        version = view.version
        assert world.work.versions.saved == {version.id: version}
        assert (version.workspace_id, version.firmware_id) == (BENCH, firmware.id)
        assert version.number == SemVer(0, 1, 0)
        assert (version.status, version.changelog, version.based_on) == (
            VersionStatus.DRAFT,
            None,
            None,
        )
        assert version.created_at == version.updated_at == firmware.updated_at == LATER
        assert (view.base, view.files) == (None, SourceFiles())
        assert world.work.firmwares.locks == [firmware.id]
        assert world.work.opened_for == [BENCH]
        assert world.work.commits == 1

    @pytest.mark.parametrize(
        ("held", "suggested"),
        [
            (["1.0.0", "1.1.0"], "1.1.1"),
            (["1.1.0", "1.3.0-rc.1"], "1.3.0-rc.2"),
            (["1.3.0-beta"], "1.3.0-beta.1"),
        ],
    )
    async def test_takes_the_successor_of_the_highest_when_no_number_is_asked(
        self, held: list[str], suggested: str
    ) -> None:
        # Requirement 5.4: the highest, the last held here, is a draft above the releases.
        world = World()
        firmware = world.hold_firmware("Weather station")
        *releases, highest = held
        for number in releases:
            world.hold_version(firmware, number, released=True)
        world.hold_version(firmware, highest)

        view = await world.start_version(BENCH, firmware.id)

        assert str(view.version.number) == suggested

    async def test_takes_the_number_asked_beside_other_drafts(self) -> None:
        # Decision 7: a 2.0.0 rewrite beside a 1.2.1 fix.
        world = World()
        firmware = world.hold_firmware("Weather station")
        fix = world.hold_version(firmware, "1.2.1")

        view = await world.start_version(BENCH, firmware.id, SemVer.parse("v2.0.0"))

        assert view.version.number == SemVer(2, 0, 0)
        assert world.work.versions.saved == {fix.id: fix, view.version.id: view.version}

    @pytest.mark.parametrize("released", [True, False], ids=["released", "draft"])
    async def test_from_a_base_copies_its_files_under_new_ids_and_leaves_it_as_it_was(
        self, released: bool
    ) -> None:
        # Requirements 5.5 and 6.6: the draft records its base, and the base keeps its files.
        # A changelog says what a version changed, so the base's isn't carried.
        world = World()
        firmware = world.hold_firmware("Weather station")
        base = world.hold_version(firmware, "1.1.0", released=released)
        config = world.hold_file(base, "config.h", "#define SDA 21\n")
        sketch = world.hold_file(base, "weather_station.ino", SKETCH)
        kept = astuple(base)

        view = await world.start_version(BENCH, firmware.id, None, base.id)

        copies = view.files.items
        assert (view.version.number, view.version.based_on) == (SemVer(1, 1, 1), base.id)
        assert (view.base, view.version.changelog) == (base, None)
        assert [(file.path, file.text) for file in copies] == [
            (sketch.path, sketch.text),
            (config.path, config.text),
        ]
        assert {file.id for file in copies}.isdisjoint({sketch.id, config.id})
        assert set(world.work.sources.of(view.version.id)) == set(copies)
        assert set(world.work.sources.of(base.id)) == {sketch, config}
        assert astuple(base) == kept
        assert world.work.commits == 1

    @pytest.mark.parametrize("elsewhere", [True, False], ids=["another firmware's", "none"])
    async def test_a_base_that_isnt_one_of_the_firmwares_versions_is_not_found(
        self, elsewhere: bool
    ) -> None:
        # Requirement 5.9: another firmware's version, or one the workspace doesn't hold.
        world = World()
        firmware = world.hold_firmware("Weather station")
        other = world.hold_version(world.hold_firmware("Pico blink"), "1.0.0", released=True)
        world.hold_file(other, "main.py", "led.toggle()\n")
        base_id = other.id if elsewhere else VersionId(uuid7())
        before = world.snapshot()

        with pytest.raises(VersionNotFoundError, match="isn't one of this firmware's"):
            await world.start_version(BENCH, firmware.id, None, base_id)

        assert world.snapshot() == before
        assert world.work.commits == 0

    async def test_refuses_a_number_another_version_holds(self) -> None:
        # Requirement 5.2: v1.1.0 is 1.1.0.
        world = World()
        firmware = world.hold_firmware("Weather station")
        world.hold_version(firmware, "1.1.0", released=True)
        before = world.snapshot()

        with pytest.raises(VersionTakenError) as refused:
            await world.start_version(BENCH, firmware.id, SemVer.parse("v1.1.0"))

        assert str(refused.value) == "this firmware already has a version 1.1.0"
        assert refused.value.field is FirmwareField.VERSION
        assert world.snapshot() == before
        assert world.work.commits == 0

    async def test_a_firmware_not_in_the_workspace_is_not_found(self) -> None:
        world = World()

        with pytest.raises(FirmwareNotFoundError, match="that firmware doesn't exist"):
            await world.start_version(BENCH, FirmwareId(uuid7()))

        assert world.work.versions.saved == {}
        assert world.work.commits == 0


class TestUpdate:
    async def test_replaces_a_drafts_number_and_changelog_under_the_firmwares_lock(self) -> None:
        # Requirement 5.7, moving the version and its firmware on (2.2). The answer is the
        # version as it opens.
        world = World()
        firmware = world.hold_firmware("Weather station")
        release = world.hold_version(firmware, "1.1.0", released=True)
        draft = world.hold_version(firmware, "1.2.0", based_on=release)
        sketch = world.hold_file(draft, "weather_station.ino", SKETCH)
        world.clock.advance(timedelta(minutes=5))

        view = await world.update_version(BENCH, draft.id, SemVer.parse("2.0.0-RC.1"), AVERAGES)

        assert view.version is draft
        assert (draft.number, draft.changelog) == (SemVer(2, 0, 0, ("rc", 1)), AVERAGES)
        assert draft.updated_at == firmware.updated_at == LATER
        assert (view.base, view.files.items) == (release, (sketch,))
        assert world.work.firmwares.locks == [firmware.id]
        assert world.work.commits == 1

    async def test_its_own_number_doesnt_count_against_it(self) -> None:
        world = World()
        firmware = world.hold_firmware("Weather station")
        world.hold_version(firmware, "1.1.0", released=True)
        draft = world.hold_version(firmware, "1.2.0")

        await world.update_version(BENCH, draft.id, SemVer.parse("v1.2.0"), AVERAGES)

        assert (draft.number, draft.changelog) == (SemVer(1, 2, 0), AVERAGES)
        assert world.work.commits == 1

    async def test_refuses_a_number_another_version_holds(self) -> None:
        # Requirement 5.2.
        world = World()
        firmware = world.hold_firmware("Weather station")
        world.hold_version(firmware, "1.1.0", released=True)
        draft = world.hold_version(firmware, "1.2.0")
        before = world.snapshot()

        with pytest.raises(VersionTakenError, match=re.escape("already has a version 1.1.0")):
            await world.update_version(BENCH, draft.id, SemVer(1, 1, 0), AVERAGES)

        assert world.snapshot() == before
        assert world.work.commits == 0

    async def test_an_edit_that_changes_nothing_commits_nothing(self) -> None:
        # The same number and changelog, typed another way.
        world = World()
        firmware = world.hold_firmware("Weather station")
        draft = world.hold_version(firmware, "1.2.0")
        draft.changelog = AVERAGES
        world.clock.advance(timedelta(minutes=5))
        before = world.snapshot()

        view = await world.update_version(
            BENCH, draft.id, SemVer.parse(" 1.2.0 "), Changelog("Averages three readings.\r\n")
        )

        assert view.version is draft
        assert world.snapshot() == before
        assert world.work.commits == 0


class TestRelease:
    async def test_marks_a_draft_released_and_records_when(self) -> None:
        # Requirement 6.1, under the firmware's lock, moving it up the list (2.2).
        world = World()
        firmware = world.hold_firmware("Weather station")
        draft = world.hold_version(firmware, "1.2.0")
        draft.changelog = AVERAGES
        sketch = world.hold_file(draft, "weather_station.ino", SKETCH)
        world.clock.advance(timedelta(minutes=5))

        view = await world.release_version(BENCH, draft.id)

        assert view.version is draft
        assert draft.status is VersionStatus.RELEASED
        assert draft.released_at == draft.updated_at == firmware.updated_at == LATER
        assert (view.base, view.files.items) == (None, (sketch,))
        assert world.work.firmwares.locks == [firmware.id]
        assert world.work.commits == 1

    async def test_a_draft_with_no_file_is_refused_and_left_a_draft(self) -> None:
        # Requirement 6.2.
        world = World()
        draft = world.hold_version(world.hold_firmware("Weather station"), "1.2.0")
        draft.changelog = AVERAGES
        before = world.snapshot()

        with pytest.raises(NoFilesError, match=re.escape("1.2.0 has no source file to release")):
            await world.release_version(BENCH, draft.id)

        assert world.snapshot() == before
        assert world.work.commits == 0

    async def test_a_draft_with_no_changelog_is_refused_on_the_changelog(self) -> None:
        # Requirement 6.3.
        world = World()
        draft = world.hold_version(world.hold_firmware("Weather station"), "1.2.0")
        world.hold_file(draft, "weather_station.ino", SKETCH)
        before = world.snapshot()

        with pytest.raises(NoChangelogError) as refused:
            await world.release_version(BENCH, draft.id)

        assert refused.value.field is FirmwareField.CHANGELOG
        assert world.snapshot() == before
        assert world.work.commits == 0


class TestDelete:
    @pytest.mark.parametrize("released", [False, True], ids=["draft", "released"])
    async def test_takes_the_version_and_its_files_and_leaves_the_others(
        self, released: bool
    ) -> None:
        # Requirements 8.1 and 8.3, under the firmware's lock, moving it up the list (2.2).
        world = World()
        firmware = world.hold_firmware("Weather station")
        kept = world.hold_version(firmware, "1.0.0", released=True)
        kept_file = world.hold_file(kept, "weather_station.ino", SKETCH)
        doomed = world.hold_version(firmware, "1.1.0", released=released)
        world.hold_file(doomed, "weather_station.ino", SKETCH)
        world.hold_file(doomed, "config.h")
        world.clock.advance(timedelta(minutes=5))
        kept_row = astuple(kept)

        await world.delete_version(BENCH, doomed.id)

        assert world.work.versions.saved == {kept.id: kept}
        assert astuple(kept) == kept_row
        assert world.work.sources.saved == {kept_file.id: (kept.id, kept_file)}
        assert firmware.updated_at == LATER
        assert world.work.firmwares.locks == [firmware.id]
        assert world.work.commits == 1

    async def test_deleting_a_base_clears_it_from_the_versions_started_from_it(self) -> None:
        # Requirement 8.2: they keep going, and open with no base.
        world = World()
        firmware = world.hold_firmware("Weather station")
        base = world.hold_version(firmware, "1.0.0", released=True)
        started = world.hold_version(firmware, "1.1.0", based_on=base)
        sketch = world.hold_file(started, "weather_station.ino", SKETCH)

        await world.delete_version(BENCH, base.id)
        view = await world.get_version(BENCH, started.id)

        assert started.based_on is None
        assert (view.version, view.base, view.files.items) == (started, None, (sketch,))


async def test_get_answers_the_version_its_base_and_its_files_in_order() -> None:
    # Requirement 5.8: sketches first, then the rest by path ignoring case (7.10). A read
    # locks nothing and commits nothing.
    world = World()
    firmware = world.hold_firmware("Weather station")
    base = world.hold_version(firmware, "1.1.0", released=True)
    world.hold_file(base, "weather_station.ino", SKETCH)
    draft = world.hold_version(firmware, "1.2.0", based_on=base)
    library = world.hold_file(draft, "Lib/bme.h")
    config = world.hold_file(draft, "config.h", "#define SDA 21\n")
    sketch = world.hold_file(draft, "weather_station.ino", SKETCH)

    view = await world.get_version(BENCH, draft.id)

    assert (view.version, view.base) == (draft, base)
    assert view.files.items == (sketch, config, library)
    assert world.work.firmwares.locks == []
    assert world.work.commits == 0


def _get(world: World, version_id: VersionId) -> Awaitable[object]:
    return world.get_version(BENCH, version_id)


def _update(world: World, version_id: VersionId) -> Awaitable[object]:
    return world.update_version(BENCH, version_id, SemVer(1, 0, 0), None)


def _release(world: World, version_id: VersionId) -> Awaitable[object]:
    return world.release_version(BENCH, version_id)


def _delete(world: World, version_id: VersionId) -> Awaitable[object]:
    return world.delete_version(BENCH, version_id)


@pytest.mark.parametrize(
    "action", [_get, _update, _release, _delete], ids=["get", "update", "release", "delete"]
)
async def test_a_version_not_in_the_workspace_is_not_found(
    action: Callable[[World, VersionId], Awaitable[object]],
) -> None:
    # Requirement 5.9: another bench's id reads the same, the fakes holding one bench.
    world = World()
    world.hold_version(world.hold_firmware("Weather station"), "1.0.0")
    before = world.snapshot()

    with pytest.raises(VersionNotFoundError, match="that version doesn't exist"):
        await action(world, VersionId(uuid7()))

    assert world.snapshot() == before
    assert world.work.firmwares.locks == []
    assert world.work.commits == 0


class TestLockVersion:
    async def test_locks_the_firmware_before_it_reads_the_version(self) -> None:
        world = World()
        firmware = world.hold_firmware("Weather station")
        version = world.hold_version(firmware, "1.0.0")
        work = world.work
        order: list[str] = []
        locked, get = work.firmwares.locked, work.versions.get

        async def locking(firmware_id: FirmwareId) -> Firmware | None:
            order.append("lock")
            return await locked(firmware_id)

        async def reading(version_id: VersionId) -> FirmwareVersion | None:
            order.append("read")
            return await get(version_id)

        work.firmwares.locked = locking  # type: ignore[method-assign]
        work.versions.get = reading  # type: ignore[method-assign]

        assert await lock_version(work, version.id) == (firmware, version)
        assert order == ["lock", "read"]

    async def test_a_version_whose_firmware_went_is_not_found(self) -> None:
        world = World()
        firmware = world.hold_firmware("Weather station")
        version = world.hold_version(firmware, "1.0.0")
        del world.work.firmwares.saved[firmware.id]

        with pytest.raises(VersionNotFoundError, match="that version doesn't exist"):
            await lock_version(world.work, version.id)

    async def test_a_version_deleted_while_it_waited_for_the_lock_is_not_found(self) -> None:
        # The write before it, holding the lock, deleted the version.
        world = World()
        version = world.hold_version(world.hold_firmware("Weather station"), "1.0.0")
        work = world.work
        locked = work.firmwares.locked

        async def locking_after_a_delete(firmware_id: FirmwareId) -> Firmware | None:
            await work.versions.remove(version)
            return await locked(firmware_id)

        work.firmwares.locked = locking_after_a_delete  # type: ignore[method-assign]

        with pytest.raises(VersionNotFoundError, match="that version doesn't exist"):
            await lock_version(work, version.id)


# --- Property 7: a released version never changes, through the use cases -------------------

# Small pools, so an edit often asks for the version's own number or changelog again.
_IDENTIFIERS: st.SearchStrategy[Identifier] = st.integers(0, 2) | st.sampled_from(["rc", "beta"])
_NUMBERS = st.builds(
    SemVer,
    st.integers(0, 2),
    st.integers(0, 2),
    st.integers(0, 2),
    st.lists(_IDENTIFIERS, max_size=2).map(tuple),
)
_CHANGELOGS = st.sampled_from(
    [AVERAGES, Changelog("Sleeps between readings."), Changelog("Fades the LED in and out.")]
)
# What the release is made with: paths that never clash, and text a draft takes.
_RELEASED_PATHS = ["weather_station.ino", "config.h", "lib/bme.h", "src/main.cpp"]
_TEXTS = ["", "#define SDA 21\n", "void loop() {}\r\n", "\tpin = 26  "]
# What the writes after it send: those, paths clashing with them in case or as a folder, and a
# path and a text a draft would refuse, so the release is seen to refuse first.
_NEW_FILES = st.builds(
    NewSourceFile,
    st.sampled_from([*_RELEASED_PATHS, "Config.h", "lib", "../secrets.h"]),
    st.sampled_from([*_TEXTS, "led\x00"]),
)


@dataclass(frozen=True)
class _Released:
    """The released version the writes are sent to: its id, and its files' ids with one more
    that no version holds."""

    version_id: VersionId
    file_ids: tuple[SourceFileId, ...]

    def file(self, which: int) -> SourceFileId:
        return self.file_ids[which % len(self.file_ids)]


@dataclass(frozen=True)
class _Edit:
    number: SemVer
    changelog: Changelog | None

    async def run(self, world: World, released: _Released) -> None:
        await world.update_version(BENCH, released.version_id, self.number, self.changelog)


@dataclass(frozen=True)
class _ReleaseAgain:
    async def run(self, world: World, released: _Released) -> None:
        await world.release_version(BENCH, released.version_id)


@dataclass(frozen=True)
class _AddFiles:
    files: tuple[NewSourceFile, ...]

    async def run(self, world: World, released: _Released) -> None:
        await world.add_source_files(BENCH, released.version_id, self.files)


@dataclass(frozen=True)
class _EditFile:
    which: int
    edit: NewSourceFile

    async def run(self, world: World, released: _Released) -> None:
        file_id = released.file(self.which)
        await world.update_source_file(BENCH, released.version_id, file_id, self.edit)


@dataclass(frozen=True)
class _RemoveFile:
    which: int

    async def run(self, world: World, released: _Released) -> None:
        await world.remove_source_file(BENCH, released.version_id, released.file(self.which))


type _Write = _Edit | _ReleaseAgain | _AddFiles | _EditFile | _RemoveFile


def _writes(number: SemVer, changelog: Changelog) -> st.SearchStrategy[_Write]:
    """Every write to a version's number, changelog or files: edits to its own number and
    changelog among them, a second release, and files a draft would take or refuse."""
    numbers = st.just(number) | _NUMBERS
    changelogs = st.just(changelog) | st.none() | _CHANGELOGS
    return (
        st.builds(_Edit, numbers, changelogs)
        | st.just(_ReleaseAgain())
        | st.builds(_AddFiles, st.lists(_NEW_FILES, min_size=1, max_size=3).map(tuple))
        | st.builds(_EditFile, st.integers(0, 3), _NEW_FILES)
        | st.builds(_RemoveFile, st.integers(0, 3))
    )


@given(data=st.data())
def test_a_released_version_never_changes(data: st.DataObject) -> None:
    """Property 7: a released version never changes.

    For any released version and any sequence of number, changelog and file writes after its
    release, every write is refused with version_released, and the number, changelog and files
    are what they were when it was released. Over the use cases: the version is started, given
    its files and its changelog, and released through them; the writes edit its number and
    changelog, its own among them, release it again, and add, edit or remove files, with paths
    and text a draft would refuse and a file it doesn't hold among them, so the release is seen
    to refuse first. Each commits nothing and leaves every stored row as it was, the
    firmware's last change included.

    **Validates: Requirements 6.4, 6.5**
    """
    number, changelog = data.draw(_NUMBERS), data.draw(_CHANGELOGS)
    paths = data.draw(
        st.lists(st.sampled_from(_RELEASED_PATHS), min_size=1, max_size=3, unique=True)
    )
    files = [NewSourceFile(path, data.draw(st.sampled_from(_TEXTS))) for path in paths]
    writes = data.draw(st.lists(_writes(number, changelog), min_size=1, max_size=6))

    async def scenario() -> None:
        world = World()
        firmware = world.hold_firmware("Weather station")
        version_id = (await world.start_version(BENCH, firmware.id, number)).version.id
        added = await world.add_source_files(BENCH, version_id, files)
        await world.update_version(BENCH, version_id, number, changelog)
        await world.release_version(BENCH, version_id)
        world.clock.advance(timedelta(minutes=5))
        released = _Released(version_id, (*(file.id for file in added), SourceFileId(uuid7())))
        before, commits = world.snapshot(), world.work.commits
        for write in writes:
            with pytest.raises(VersionReleasedError) as refused:
                await write.run(world, released)
            assert refused.value.code is FirmwareRefusal.VERSION_RELEASED
            assert world.snapshot() == before
            assert world.work.commits == commits
        view = await world.get_version(BENCH, version_id)
        assert (view.version.number, view.version.changelog) == (number, changelog)
        assert view.files.items == added

    anyio.run(scenario)
