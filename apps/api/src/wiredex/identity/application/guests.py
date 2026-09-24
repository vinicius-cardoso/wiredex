"""Guest accounts after their invitation ends (ADR 0007)."""

from collections.abc import Callable

from wiredex.identity.application.ports import IdentityUnitOfWork
from wiredex.identity.domain.model import User
from wiredex.identity.domain.values import WorkspaceKind
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


async def _remove(work: IdentityUnitOfWork, guest: User) -> None:
    for membership in await work.memberships.of_user(guest.id):
        workspace = await work.workspaces.get(membership.workspace_id)
        if workspace is not None and workspace.kind is WorkspaceKind.DEMO:
            await work.workspaces.remove(workspace)
    await work.users.remove(guest)
