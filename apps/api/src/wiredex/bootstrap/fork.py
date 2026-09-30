"""One transaction across projects and firmware, for a fork.

The one file that sees both modules for a fork (13-firmware-versions decision 4, requirement
12.1). Projects copies what a revision holds through the `RevisionContent`s its unit of work
carries (08's decision 6) and imports nothing from firmware. Firmware offers
`CopyRevisionLinks` over a `FirmwareRepositories`, which never opens or commits a transaction of
its own. This file joins them: the fourth use of 07's shared-session pattern, after
`bootstrap/intake.py`, `bootstrap/build.py` and `bootstrap/netlist.py`, and the first time 08's
seam carries content another module keeps.

A fork copies its source's BOM lines, then its nets, then the firmware it runs, in the fork's
transaction, on its connection, under the one workspace setting the projects unit of work
applied, so row-level security scopes both modules' rows, and the fork's one `commit()` keeps
the revision and every copy or, leaving without it, none of them (requirements 4.1, 4.3).
`ForkRevision` doesn't change (08's requirement 6.7): only the unit of work it is built over
does.
"""

from typing import Self

from wiredex.firmware.application.links import CopyRevisionLinks
from wiredex.firmware.domain.values import RevisionId as FirmwareRevisionId
from wiredex.firmware.domain.values import WorkspaceId as FirmwareWorkspaceId
from wiredex.firmware.infrastructure.unit_of_work import SqlFirmwareRepositories
from wiredex.projects.domain.revision import Revision
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork


class FirmwareLinksContent:
    """Projects' `RevisionContent` over firmware's `CopyRevisionLinks` (decision 4): the fork
    runs the firmware its source runs, whatever the source's status (requirement 4.4).

    The links are dated with the fork's creation, the moment it starts running them, and the
    firmware they name move up the firmware list with it (requirement 2.2).
    """

    def __init__(self, links: CopyRevisionLinks) -> None:
        self._links = links

    async def copy(self, source: Revision, target: Revision) -> None:
        # The same UUIDs under each module's own name: neither imports the other's domain.
        await self._links.copy(
            FirmwareRevisionId(source.id), FirmwareRevisionId(target.id), target.created_at
        )


class SqlForkUnitOfWork(SqlProjectsUnitOfWork):
    """08's unit of work with firmware's links as a third content, after the BOM and netlist.

    The base opens the session, sets `app.workspace_id` for the transaction, binds projects'
    repositories and registers 09's `CopyBomLines` and 11's `CopyNetlist`. Firmware's
    repositories then join that same session under the same workspace, wrapped as
    `FirmwareLinksContent` and registered last. Commit and rollback stay 08's.
    """

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        # The same UUID under each module's own name: neither imports the other's domain.
        firmware = SqlFirmwareRepositories(self.session, FirmwareWorkspaceId(self._workspace))
        links = FirmwareLinksContent(CopyRevisionLinks(firmware))
        self.revision_contents = (*self.revision_contents, links)
        return self
