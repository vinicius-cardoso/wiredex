"""Guest accounts after their invitation ends (ADR 0007)."""

from collections.abc import Callable

from wiredex.identity.application.ports import IdentityUnitOfWork
from wiredex.identity.domain.model import User
from wiredex.identity.domain.values import WorkspaceId, WorkspaceKind
from wiredex.shared_kernel.application.ports import Clock


class RemoveExpiredGuests:
    """Deletes guests whose access ended, with their demo workspaces and sessions.

    Part of the nightly `wiredex demo reset` (ADR 0011). Only accounts with an expiry
    date are guests, and only demo workspaces go with them.
    """

    def __init__(self, unit_of_work: Callable[[], IdentityUnitOfWork], clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(self) -> int:
        """Returns how many guests were removed."""
        async with self._unit_of_work() as work:
            guests = await work.users.expired(self._clock.now())
            for guest in guests:
                await _remove(work, guest)
            await work.commit()
        return len(guests)


class ListDemoWorkspaces:
    """The demo benches that exist, so every module can restore its sample data in them.

    The other half of the nightly `wiredex demo reset`: identity owns workspaces and knows
    nothing about parts, so it answers which benches are demo ones and the composition root
    hands the ids to the modules that seed them (ADR 0007, requirement 6.6).
    """

    def __init__(self, unit_of_work: Callable[[], IdentityUnitOfWork]) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self) -> list[WorkspaceId]:
        async with self._unit_of_work() as work:
            benches = await work.workspaces.of_kind(WorkspaceKind.DEMO)
        return [bench.id for bench in benches]


class ListAllWorkspaces:
    """Every workspace there is, so the nightly prune can sweep each one (ADR 0011).

    The prune deletes orphaned files across all workspaces, personal and demo alike, so
    unlike the demo reset it isn't a matter of kind: the composition root hands the ids to
    the files module, which owns nothing about workspaces.
    """

    def __init__(self, unit_of_work: Callable[[], IdentityUnitOfWork]) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self) -> list[WorkspaceId]:
        async with self._unit_of_work() as work:
            workspaces = await work.workspaces.all()
        return [workspace.id for workspace in workspaces]


async def _remove(work: IdentityUnitOfWork, guest: User) -> None:
    for membership in await work.memberships.of_user(guest.id):
        workspace = await work.workspaces.get(membership.workspace_id)
        if workspace is not None and workspace.kind is WorkspaceKind.DEMO:
            await work.workspaces.remove(workspace)
    await work.users.remove(guest)
