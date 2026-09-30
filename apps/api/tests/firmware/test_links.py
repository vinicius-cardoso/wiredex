"""The revisions a firmware runs on, over the in-memory firmware fakes: linking, unlinking, a
fork's copy, and the links resolved at every read."""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import uuid7

import anyio
import pytest
from hypothesis import given
from hypothesis import strategies as st

from support.firmware import BENCH, NOW, World
from wiredex.firmware.domain.errors import FirmwareNotFoundError, RevisionNotFoundError
from wiredex.firmware.domain.firmware import FirmwareDetails
from wiredex.firmware.domain.values import (
    BoardTarget,
    FirmwareId,
    FirmwareName,
    Framework,
    RevisionId,
)

pytestmark = pytest.mark.anyio

LATER = NOW + timedelta(minutes=5)


class TestLink:
    async def test_records_it_and_moves_the_firmware_up_under_its_lock(self) -> None:
        # Requirements 3.1 and 2.2. Firmware's facts of a revision carry no status, so none can
        # refuse a link: what a revision runs changes after it is built (decision 2).
        world = World()
        firmware = world.hold_firmware("Weather station")
        revision = world.directory.hold()
        world.clock.advance(timedelta(minutes=5))

        await world.link_revision(BENCH, firmware.id, revision.revision_id)

        assert world.work.links.saved == {(firmware.id, revision.revision_id): LATER}
        assert firmware.updated_at == LATER
        assert world.work.firmwares.locks == [firmware.id]
        assert world.work.opened_for == [BENCH]
        assert world.work.commits == 1

    async def test_a_repeated_link_writes_nothing(self) -> None:
        # Requirement 3.1: the link keeps its date, so the order it was linked in stays.
        world = World()
        firmware = world.hold_firmware("Weather station")
        revision = world.directory.hold()
        world.hold_link(firmware, revision.revision_id)
        world.clock.advance(timedelta(minutes=5))

        await world.link_revision(BENCH, firmware.id, revision.revision_id)

        assert world.work.links.saved == {(firmware.id, revision.revision_id): NOW}
        assert firmware.updated_at == NOW
        assert world.work.commits == 0

    async def test_a_revision_the_workspace_doesnt_hold_is_not_found(self) -> None:
        # Requirement 3.7: another bench's revision, or one deleted, even one linked before.
        world = World()
        firmware = world.hold_firmware("Weather station")

        with pytest.raises(RevisionNotFoundError, match="that revision doesn't exist"):
            await world.link_revision(BENCH, firmware.id, RevisionId(uuid7()))

        assert world.work.links.saved == {}
        assert firmware.updated_at == NOW
        assert world.work.commits == 0


class TestUnlink:
    async def test_removes_it_and_moves_the_firmware_up_under_its_lock(self) -> None:
        # Requirements 3.2 and 2.2; the firmware's other link stays.
        world = World()
        firmware = world.hold_firmware("Weather station")
        breadboard, perfboard = world.directory.hold(label="A"), world.directory.hold(label="B")
        world.hold_link(firmware, breadboard.revision_id)
        world.hold_link(firmware, perfboard.revision_id)
        world.clock.advance(timedelta(minutes=5))

        await world.unlink_revision(BENCH, firmware.id, breadboard.revision_id)

        assert world.work.links.saved == {(firmware.id, perfboard.revision_id): NOW}
        assert firmware.updated_at == LATER
        assert world.work.firmwares.locks == [firmware.id]
        assert world.work.commits == 1

    async def test_a_missing_link_answers_success_and_writes_nothing(self) -> None:
        # Requirement 3.2, for a revision it never ran on and one the directory never held.
        world = World()
        firmware = world.hold_firmware("Weather station")
        world.clock.advance(timedelta(minutes=5))

        await world.unlink_revision(BENCH, firmware.id, world.directory.hold().revision_id)
        await world.unlink_revision(BENCH, firmware.id, RevisionId(uuid7()))

        assert firmware.updated_at == NOW
        assert world.work.commits == 0

    async def test_a_link_to_a_revision_the_workspace_lost_is_removed_all_the_same(self) -> None:
        # Requirement 3.6: the link refuses nothing because its revision went.
        world = World()
        firmware = world.hold_firmware("Weather station")
        lost = world.directory.hold()
        world.hold_link(firmware, lost.revision_id)
        del world.directory.held[lost.revision_id]

        await world.unlink_revision(BENCH, firmware.id, lost.revision_id)

        assert world.work.links.saved == {}
        assert world.work.commits == 1


def _link(world: World, firmware_id: FirmwareId) -> Awaitable[None]:
    return world.link_revision(BENCH, firmware_id, world.directory.hold().revision_id)


def _unlink(world: World, firmware_id: FirmwareId) -> Awaitable[None]:
    return world.unlink_revision(BENCH, firmware_id, world.directory.hold().revision_id)


@pytest.mark.parametrize("action", [_link, _unlink], ids=["link", "unlink"])
async def test_a_firmware_not_in_the_workspace_is_not_found(
    action: Callable[[World, FirmwareId], Awaitable[None]],
) -> None:
    world = World()

    with pytest.raises(FirmwareNotFoundError, match="that firmware doesn't exist"):
        await action(world, FirmwareId(uuid7()))

    assert world.work.links.saved == {}
    assert world.work.commits == 0


async def test_a_link_to_a_revision_the_workspace_lost_is_kept_and_refuses_nothing() -> None:
    # Requirement 3.6 (decision 3): the page and an edit's answer leave it out, the list keeps
    # the firmware, and the link stays for a trash to bring the revision back to.
    world = World()
    firmware = world.hold_firmware("Weather station")
    lost, kept = world.directory.hold(label="A"), world.directory.hold(label="B")
    world.hold_link(firmware, lost.revision_id)
    world.hold_link(firmware, kept.revision_id, minutes=1)
    del world.directory.held[lost.revision_id]
    renamed = FirmwareDetails(
        FirmwareName("Weather station v2"), BoardTarget("esp32:esp32:esp32"), Framework.ARDUINO
    )

    page = await world.get_firmware(BENCH, firmware.id)
    edited = await world.update_firmware(BENCH, firmware.id, renamed)
    rows = await world.list_firmware(BENCH)

    assert page.runs_on == edited.runs_on == (kept,)
    assert [row.firmware for row in rows] == [firmware]
    assert (firmware.id, lost.revision_id) in world.work.links.saved


async def test_a_forks_copy_dates_its_links_and_moves_their_firmware_up_uncommitted() -> None:
    # Decision 4: the fork's creation dates its links, and every firmware it now runs moves up
    # the list (requirement 2.2). The copy never commits: the fork's unit of work does (4.3).
    world = World()
    weather = world.hold_firmware("Weather station")
    greenhouse = world.hold_firmware("Greenhouse controller")
    pico = world.hold_firmware("Pico blink")
    source, other, fork = RevisionId(uuid7()), RevisionId(uuid7()), RevisionId(uuid7())
    world.hold_link(weather, source)
    world.hold_link(greenhouse, source, minutes=1)
    world.hold_link(pico, other)

    await world.copy_revision_links.copy(source, fork, LATER)

    assert world.work.links.saved == {
        (weather.id, source): NOW,
        (greenhouse.id, source): NOW + timedelta(minutes=1),
        (pico.id, other): NOW,
        (weather.id, fork): LATER,
        (greenhouse.id, fork): LATER,
    }
    assert (weather.updated_at, greenhouse.updated_at, pico.updated_at) == (LATER, LATER, NOW)
    assert world.work.commits == 0


# --- Property 8: a fork copies exactly its source's links -----------------------------------

_FIRMWARE = 3
_REVISIONS = 4
# Links between a few firmware and a few revisions, each made so many minutes after NOW: small
# pools, so revisions share firmware and the source often has several links, or none.
_LINKS = st.dictionaries(
    st.tuples(st.integers(0, _FIRMWARE - 1), st.integers(0, _REVISIONS - 1)), st.integers(0, 3)
)


@given(links=_LINKS, source=st.integers(0, _REVISIONS - 1))
def test_a_fork_copies_exactly_its_sources_links(
    links: dict[tuple[int, int], int], source: int
) -> None:
    """Property 8: a fork copies exactly its source's links.

    For any links among any firmware and revisions, and a fork's new revision, which holds no
    link yet, after CopyRevisionLinks.copy(source, fork, at) the firmware linked to the fork
    are those linked to the source, and every other revision's links, the source's among them,
    are unchanged, dates included.

    **Validates: Requirements 4.1, 4.2**
    """
    world = World()
    firmware = [world.hold_firmware(f"Firmware {number}") for number in range(_FIRMWARE)]
    revisions = [RevisionId(uuid7()) for _ in range(_REVISIONS)]
    for (which, revision), minutes in links.items():
        world.hold_link(firmware[which], revisions[revision], minutes=minutes)
    before = dict(world.work.links.saved)
    fork = RevisionId(uuid7())

    anyio.run(world.copy_revision_links.copy, revisions[source], fork, LATER)

    after = world.work.links.saved
    copied = {firmware_id for firmware_id, revision_id in after if revision_id == fork}
    assert copied == {
        firmware_id for firmware_id, revision_id in before if revision_id == revisions[source]
    }
    assert {key: at for key, at in after.items() if key[1] != fork} == before


# --- Property 9: links resolve at every read ------------------------------------------------

_POOL = 6


@given(
    linked=st.dictionaries(st.integers(0, _POOL - 1), st.integers(0, 3)),
    others=st.sets(st.integers(0, _POOL - 1)),
    held=st.sets(st.integers(0, _POOL - 1)),
)
def test_links_resolve_at_every_read(
    linked: dict[int, int], others: set[int], held: set[int]
) -> None:
    """Property 9: links resolve at every read.

    For any links of a firmware, each made so many minutes after NOW, any links of another
    firmware, and any directory holding some of the revisions, the firmware's runs_on is exactly
    its linked revisions the directory holds, each as the directory names it, in link order:
    oldest first, and two made at one instant by the revision's id.

    **Validates: Requirements 3.5, 3.6**
    """
    world = World()
    firmware = world.hold_firmware("Weather station")
    other = world.hold_firmware("Greenhouse controller")
    revisions = [world.directory.hold(label=f"R{number}") for number in range(_POOL)]
    for which, minutes in linked.items():
        world.hold_link(firmware, revisions[which].revision_id, minutes=minutes)
    for which in others:
        world.hold_link(other, revisions[which].revision_id)
    for which in set(range(_POOL)) - held:
        del world.directory.held[revisions[which].revision_id]

    view = anyio.run(world.get_firmware, BENCH, firmware.id)

    order = sorted(linked, key=lambda which: (linked[which], revisions[which].revision_id))
    assert view.runs_on == tuple(revisions[which] for which in order if which in held)
