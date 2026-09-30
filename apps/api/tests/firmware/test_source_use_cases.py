"""The source-file use cases over the in-memory firmware fakes: adding a batch to a draft,
editing one of its files and removing one.

The fakes write straight into their stores and count commits, so a refused change is one that
left the stores as they were and committed nothing. A released version refusing every file
write is property 7, in `test_version_use_cases.py`.
"""

from datetime import timedelta
from uuid import uuid7

import pytest

from support.firmware import BENCH, NOW, World
from wiredex.firmware.application.ports import NewSourceFile
from wiredex.firmware.domain.errors import (
    FirmwareRefusalError,
    InvalidPathError,
    NotTextError,
    PathTakenError,
    SourceFileNotFoundError,
    TooManyFilesError,
    VersionNotFoundError,
    VersionTooLargeError,
)
from wiredex.firmware.domain.source import MAX_VERSION_BYTES, SourceFile
from wiredex.firmware.domain.values import SourceFileId, VersionId

pytestmark = pytest.mark.anyio

LATER = NOW + timedelta(minutes=5)
SKETCH = "void setup() {}\nvoid loop() {}\n"


class Bench:
    """A world with a draft of the weather station holding its sketch, and a clock five
    minutes on, so a write's touch shows."""

    def __init__(self) -> None:
        self.world = World()
        self.firmware = self.world.hold_firmware("Weather station")
        self.draft = self.world.hold_version(self.firmware, "1.2.0")
        self.sketch = self.world.hold_file(self.draft, "weather_station.ino", SKETCH)
        self.world.clock.advance(timedelta(minutes=5))

    def files(self) -> set[SourceFile]:
        return set(self.world.work.sources.of(self.draft.id))


class TestAdd:
    async def test_adds_a_batch_in_one_commit_and_answers_it_in_the_versions_order(self) -> None:
        # Requirements 7.1 and 7.10: the text kept as sent but for its line endings (7.4), and
        # the version and its firmware moved on (2.2).
        bench = Bench()
        batch = [
            NewSourceFile("src\\sensor.cpp", "\tread();  \r\n\r\n"),
            NewSourceFile("config.h", "#define SDA 21"),
        ]

        added = await bench.world.add_source_files(BENCH, bench.draft.id, batch)

        assert [(str(file.path), str(file.text)) for file in added] == [
            ("config.h", "#define SDA 21"),
            ("src/sensor.cpp", "\tread();  \n\n"),
        ]
        assert bench.files() == {bench.sketch, *added}
        assert len({bench.sketch.id, *(file.id for file in added)}) == 3
        assert bench.draft.updated_at == bench.firmware.updated_at == LATER
        assert bench.world.work.firmwares.locks == [bench.firmware.id]
        assert bench.world.work.opened_for == [BENCH]
        assert bench.world.work.commits == 1

    @pytest.mark.parametrize(
        ("batch", "refusal", "item"),
        [
            pytest.param(
                [NewSourceFile("config.h", ""), NewSourceFile("../secrets.h", "")],
                InvalidPathError,
                "../secrets.h",
                id="a path its rules refuse",
            ),
            pytest.param(
                [NewSourceFile("config.h", ""), NewSourceFile("logo.h", "\x89PNG\x00")],
                NotTextError,
                "logo.h",
                id="text with a NUL",
            ),
            pytest.param(
                [NewSourceFile("config.h", ""), NewSourceFile("Weather_Station.ino", "")],
                PathTakenError,
                "Weather_Station.ino",
                id="a path another file holds",
            ),
            pytest.param(
                [NewSourceFile("lib/bme.h", ""), NewSourceFile("lib", "")],
                PathTakenError,
                "lib",
                id="a folder of another file of the batch",
            ),
        ],
    )
    async def test_a_batch_is_refused_whole(
        self, batch: list[NewSourceFile], refusal: type[FirmwareRefusalError], item: str
    ) -> None:
        # Requirements 7.1, 7.2, 7.3 and 7.5: the batch's good files aren't kept either, and
        # the refusal names the file it is about.
        bench = Bench()
        before = bench.world.snapshot()

        with pytest.raises(refusal) as refused:
            await bench.world.add_source_files(BENCH, bench.draft.id, batch)

        assert refused.value.item == item
        assert bench.world.snapshot() == before
        assert bench.world.work.commits == 0

    async def test_an_empty_batch_writes_nothing(self) -> None:
        # The API sends 1 to 100 files; a caller sending none has changed nothing.
        bench = Bench()
        before = bench.world.snapshot()

        assert await bench.world.add_source_files(BENCH, bench.draft.id, []) == ()
        assert bench.world.snapshot() == before
        assert bench.world.work.commits == 0

    async def test_a_batch_past_100_files_is_refused(self) -> None:
        # Requirement 7.6: the sketch and 98 more make 99, and a batch of two 101.
        bench = Bench()
        for number in range(98):
            bench.world.hold_file(bench.draft, f"lib/part_{number}.h")
        before = bench.world.snapshot()
        batch = [NewSourceFile("a.h", ""), NewSourceFile("b.h", "")]

        with pytest.raises(TooManyFilesError, match="at most 100 files, not 101"):
            await bench.world.add_source_files(BENCH, bench.draft.id, batch)

        assert bench.world.snapshot() == before
        assert bench.world.work.commits == 0

    async def test_a_batch_past_the_versions_size_is_refused_saying_how_much_room_is_left(
        self,
    ) -> None:
        # Requirement 7.7: 1,048,000 bytes held leave 576, and the batch brings 1,000.
        bench = Bench()
        bench.world.hold_file(bench.draft, "data.h", "a" * (1_048_000 - len(SKETCH)))
        before = bench.world.snapshot()
        batch = [NewSourceFile("a.h", "b" * 400), NewSourceFile("b.h", "c" * 600)]

        with pytest.raises(VersionTooLargeError) as refused:
            await bench.world.add_source_files(BENCH, bench.draft.id, batch)

        assert str(refused.value) == (
            "1,000 bytes won't fit: a version holds 1,048,576 bytes of source, and this one "
            "has 576 left"
        )
        assert bench.world.snapshot() == before
        assert bench.world.work.commits == 0


class TestUpdate:
    async def test_replaces_a_files_path_and_text_under_its_id(self) -> None:
        # Requirement 7.8 and decision 10: a rename keeps the file, and the version and its
        # firmware move on (2.2).
        bench = Bench()
        config = bench.world.hold_file(bench.draft, "config.h", "#define SDA 21\n")
        edit = NewSourceFile("include/Config.h", "#define SDA 21\r\n#define SCL 22\r\n")

        edited = await bench.world.update_source_file(BENCH, bench.draft.id, config.id, edit)

        assert edited.id == config.id
        assert (str(edited.path), str(edited.text)) == (
            "include/Config.h",
            "#define SDA 21\n#define SCL 22\n",
        )
        assert bench.files() == {bench.sketch, edited}
        assert bench.draft.updated_at == bench.firmware.updated_at == LATER
        assert bench.world.work.firmwares.locks == [bench.firmware.id]
        assert bench.world.work.commits == 1

    async def test_its_own_path_and_bytes_dont_count_against_it(self) -> None:
        # Requirement 7.8: the sketch renamed in another case and grown to fill the version.
        bench = Bench()
        edit = NewSourceFile("Weather_Station.ino", "a" * MAX_VERSION_BYTES)

        edited = await bench.world.update_source_file(BENCH, bench.draft.id, bench.sketch.id, edit)

        assert str(edited.path) == "Weather_Station.ino"
        assert edited.text.size == MAX_VERSION_BYTES
        assert bench.files() == {edited}
        assert bench.world.work.commits == 1

    async def test_the_same_path_and_text_write_nothing(self) -> None:
        # Requirement 7.8: typed again, with spaces around the path and CRLF line endings.
        bench = Bench()
        before = bench.world.snapshot()
        edit = NewSourceFile(" weather_station.ino ", SKETCH.replace("\n", "\r\n"))

        edited = await bench.world.update_source_file(BENCH, bench.draft.id, bench.sketch.id, edit)

        assert edited == bench.sketch
        assert bench.world.snapshot() == before
        assert bench.world.work.commits == 0

    async def test_a_path_another_file_holds_is_refused_naming_both(self) -> None:
        # Requirement 7.3.
        bench = Bench()
        config = bench.world.hold_file(bench.draft, "config.h")
        before = bench.world.snapshot()
        edit = NewSourceFile("Weather_station.INO", "")

        with pytest.raises(PathTakenError) as refused:
            await bench.world.update_source_file(BENCH, bench.draft.id, config.id, edit)

        assert str(refused.value) == (
            "Weather_station.INO and weather_station.ino are one path to Windows and macOS"
        )
        assert refused.value.item == "Weather_station.INO"
        assert bench.world.snapshot() == before
        assert bench.world.work.commits == 0


async def test_remove_deletes_the_file_and_moves_the_version_on() -> None:
    # Requirement 7.9, under the firmware's lock (2.2).
    bench = Bench()
    config = bench.world.hold_file(bench.draft, "config.h")

    await bench.world.remove_source_file(BENCH, bench.draft.id, config.id)

    assert bench.files() == {bench.sketch}
    assert bench.draft.updated_at == bench.firmware.updated_at == LATER
    assert bench.world.work.firmwares.locks == [bench.firmware.id]
    assert bench.world.work.commits == 1


async def _write(world: World, write: str, version_id: VersionId, file_id: SourceFileId) -> None:
    config = NewSourceFile("config.h", "#define SDA 21\n")
    match write:
        case "add":
            await world.add_source_files(BENCH, version_id, [config])
        case "edit":
            await world.update_source_file(BENCH, version_id, file_id, config)
        case _:
            await world.remove_source_file(BENCH, version_id, file_id)


@pytest.mark.parametrize("write", ["add", "edit", "remove"])
async def test_a_version_not_in_the_workspace_is_not_found(write: str) -> None:
    # Requirement 9.2: another bench's id reads the same, the fakes holding one bench.
    bench = Bench()
    before = bench.world.snapshot()

    with pytest.raises(VersionNotFoundError, match="that version doesn't exist"):
        await _write(bench.world, write, VersionId(uuid7()), bench.sketch.id)

    assert bench.world.snapshot() == before
    assert bench.world.work.firmwares.locks == []
    assert bench.world.work.commits == 0


@pytest.mark.parametrize("write", ["edit", "remove"])
@pytest.mark.parametrize("elsewhere", [True, False], ids=["another version's", "none"])
async def test_a_file_the_version_doesnt_hold_is_not_found(write: str, elsewhere: bool) -> None:
    # Requirement 7.11: the firmware's other draft's file, or one no version holds.
    bench = Bench()
    other = bench.world.hold_file(bench.world.hold_version(bench.firmware, "2.0.0"), "a.h")
    file_id = other.id if elsewhere else SourceFileId(uuid7())
    before = bench.world.snapshot()

    with pytest.raises(SourceFileNotFoundError, match="that file isn't in this version"):
        await _write(bench.world, write, bench.draft.id, file_id)

    assert bench.world.snapshot() == before
    assert bench.world.work.commits == 0
