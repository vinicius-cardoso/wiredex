"""A guest's demo bench, filled: what the command line and the app both do to invite one.

Only the composition root knows every module, which is what keeps them apart (ADR 0001): the
invitation is identity's, and the samples that fill the bench belong to the catalog, the
inventory, the projects and the firmware.
"""

from collections.abc import Sequence
from uuid import UUID

from wiredex.bootstrap.catalog import restore_sample_catalog_use_case
from wiredex.bootstrap.firmware_demo import restore_sample_firmware_use_case
from wiredex.bootstrap.history import clear_history_use_case
from wiredex.bootstrap.identity import invite_guest_use_case
from wiredex.bootstrap.inventory_demo import restore_sample_inventory_use_case
from wiredex.bootstrap.projects_demo import restore_sample_projects_use_case
from wiredex.bootstrap.settings import Settings
from wiredex.catalog.domain.values import WorkspaceId
from wiredex.firmware.domain.values import WorkspaceId as FirmwareWorkspaceId
from wiredex.history.domain.values import WorkspaceId as HistoryWorkspaceId
from wiredex.identity.application.create_account import CreatedAccount, GuestInvitation
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId


async def invite_with_bench(settings: Settings, invitation: GuestInvitation) -> CreatedAccount:
    """The guest's account and demo workspace, then the sample data into it."""
    async with invite_guest_use_case(settings) as invite_guest:
        invited = await invite_guest(invitation)
    # A new bench starts with the same sample data the nightly reset restores, not half empty
    # until the night comes (decision 16 of 08-projects-and-revisions).
    await restore_benches(settings, [invited.workspace_id])
    return invited


async def restore_benches(settings: Settings, benches: Sequence[UUID]) -> None:
    """Every module's sample data into each bench, the restores opened once for them all.

    The reset and the invite both come here, so a new bench holds exactly what a reset one
    does (decision 16 of 08-projects-and-revisions). Identity's WorkspaceId, the catalog's,
    the inventory's, the projects' and the firmware's are the same UUID under one name per
    module: no module imports another's domain.
    """
    async with (
        restore_sample_catalog_use_case(settings) as restore_sample_catalog,
        restore_sample_inventory_use_case(settings) as restore_sample_inventory,
        restore_sample_projects_use_case(settings) as restore_sample_projects,
        restore_sample_firmware_use_case(settings) as restore_sample_firmware,
        clear_history_use_case(settings) as clear_history,
    ):
        for bench in benches:
            await restore_sample_catalog(WorkspaceId(bench))
            # Stock points at parts, so inventory is restored after the catalog's parts are
            # back (requirement 8.6): the sample stock's part ids are the ones just written.
            await restore_sample_inventory(InventoryWorkspaceId(bench))
            # Projects after both: 09's sample BOM lines point at the sample parts.
            await restore_sample_projects(ProjectsWorkspaceId(bench))
            # Firmware last: the samples run on the sample revisions, found by project name
            # and label once the projects' restore has minted their ids (13's requirement
            # 10.1), and the sample flashes go onto the boards inventory received, the ESP32
            # recording the revision projects' restore reserved it for (15's requirement 7.1).
            await restore_sample_firmware(FirmwareWorkspaceId(bench))
            # And its history last: what the clearing and the seeding wrote is no guest's doing,
            # so the bench starts the day with none (17-history, requirement 5.4).
            await clear_history(HistoryWorkspaceId(bench))
