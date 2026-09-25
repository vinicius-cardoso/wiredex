from datetime import timedelta

import pytest

from support.identity import InMemoryIdentity, ManualClock, NewIds, PlainHasher
from wiredex.identity.application.create_account import (
    AccountServices,
    CreateAccount,
    GuestInvitation,
    InviteGuest,
    NewAccount,
)
from wiredex.identity.application.guests import (
    ListAllWorkspaces,
    ListDemoWorkspaces,
    RemoveExpiredGuests,
)
from wiredex.identity.domain.values import (
    Email,
    GuestLifetime,
    Name,
    Password,
    WorkspaceKind,
)

pytestmark = pytest.mark.anyio

PASSWORD = Password("generated password")


class Bench:
    """An owner and two guests, one invited for a day and one for a week."""

    def __init__(self) -> None:
        self.identity = InMemoryIdentity()
        self.clock = ManualClock()
        services = AccountServices(self.clock, NewIds(), PlainHasher())
        self.create = CreateAccount(lambda: self.identity, services)
        self.invite = InviteGuest(lambda: self.identity, services)
        self.remove_expired = RemoveExpiredGuests(lambda: self.identity, self.clock)
        self.demo_workspaces = ListDemoWorkspaces(lambda: self.identity)
        self.all_workspaces = ListAllWorkspaces(lambda: self.identity)

    async def guest(self, email: str, lifetime: str) -> None:
        account = NewAccount(Email(email), Name("Guest"), PASSWORD)
        await self.invite(GuestInvitation(account, GuestLifetime.parse(lifetime)))

    def emails(self) -> set[str]:
        return {user.email.value for user in self.identity.users.saved.values()}


@pytest.fixture
async def bench() -> Bench:
    bench = Bench()
    await bench.create(NewAccount(Email("owner@example.com"), Name("Owner"), PASSWORD))
    await bench.guest("day@example.com", "1d")
    await bench.guest("week@example.com", "7d")
    return bench


async def test_nobody_is_removed_before_their_access_ends(bench: Bench) -> None:
    assert await bench.remove_expired() == 0
    assert len(bench.emails()) == 3


async def test_expired_guests_go_with_their_demo_workspaces(bench: Bench) -> None:
    bench.clock.advance(timedelta(days=1))

    assert await bench.remove_expired() == 1
    assert bench.emails() == {"owner@example.com", "week@example.com"}
    assert len(bench.identity.workspaces.saved) == 2  # the owner's and the other guest's


async def test_the_owner_is_never_removed(bench: Bench) -> None:
    bench.clock.advance(timedelta(days=3650))

    await bench.remove_expired()

    assert bench.emails() == {"owner@example.com"}
    assert [w.name for w in bench.identity.workspaces.saved.values()] == [Name("Owner")]


async def test_only_the_guests_benches_are_demo_workspaces(bench: Bench) -> None:
    """What the reset hands to the modules that seed sample data: the guests' benches."""
    demo = await bench.demo_workspaces()

    kinds = {w.id: w.kind for w in bench.identity.workspaces.saved.values()}
    assert len(demo) == 2
    assert {kinds[workspace_id] for workspace_id in demo} == {WorkspaceKind.DEMO}


async def test_a_removed_guests_bench_is_no_longer_restored(bench: Bench) -> None:
    bench.clock.advance(timedelta(days=1))

    await bench.remove_expired()

    assert len(await bench.demo_workspaces()) == 1


async def test_every_workspace_is_listed_for_the_prune(bench: Bench) -> None:
    """What the nightly prune sweeps: every workspace, the owner's personal one included."""
    all_ids = await bench.all_workspaces()

    saved = bench.identity.workspaces.saved
    assert set(all_ids) == set(saved)
    assert len(all_ids) == 3  # the owner's, and the two guests'
    assert WorkspaceKind.PERSONAL in {saved[workspace_id].kind for workspace_id in all_ids}
