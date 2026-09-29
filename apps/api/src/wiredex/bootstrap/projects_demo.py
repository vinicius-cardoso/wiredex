"""Wiring for the projects part of `wiredex demo reset` and `wiredex demo invite`.

Kept out of `bootstrap/projects.py` on purpose, as `inventory_demo.py` is kept out of
`bootstrap/inventory.py`: this is only the demo's wiring, over an engine of its own for one
run of the command (ADR 0011). The sample BOM lines name their parts, so this is also where
catalog answers for them: `AddBomLine` asks about each part through `CatalogPartLookup`, and
the bench's sample parts are read by name through catalog's `ListParts` once the catalog's
restore has minted their ids (09's requirement 10.2).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from wiredex.bootstrap.build import SqlBuildUnitOfWork
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.parts import CatalogPartLookup
from wiredex.bootstrap.settings import Settings
from wiredex.catalog.application.parts import DescribeParts, ListParts
from wiredex.catalog.application.ports import PartQuery
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork
from wiredex.projects.application.bom import AddBomLine
from wiredex.projects.application.demo import RestoreSampleProjects, SampleBoms, SampleWrites
from wiredex.projects.application.lifecycle import ReserveRevision
from wiredex.projects.application.projects import CreateProject
from wiredex.projects.application.revisions import ForkRevision, UpdateRevision
from wiredex.projects.domain.values import PartId, WorkspaceId
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator


@asynccontextmanager
async def restore_sample_projects_use_case(
    settings: Settings,
) -> AsyncIterator[RestoreSampleProjects]:
    """RestoreSampleProjects over Postgres, for one run of a demo command (decision 16)."""
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    clock, ids = SystemClock(), Uuid7Generator()

    def unit_of_work(workspace_id: WorkspaceId) -> SqlProjectsUnitOfWork:
        return SqlProjectsUnitOfWork(session_factory, workspace_id, ids)

    def build_unit_of_work(workspace_id: WorkspaceId) -> SqlBuildUnitOfWork:
        # The reserve is one transaction across projects, inventory and catalog on one session
        # (decision 8), so the demo can't set aside stock the product couldn't (decision 9).
        return SqlBuildUnitOfWork(session_factory, workspace_id, clock, ids)

    def catalog_unit_of_work(workspace_id: CatalogWorkspaceId) -> SqlCatalogUnitOfWork:
        return SqlCatalogUnitOfWork(session_factory, workspace_id)

    parts = CatalogPartLookup(DescribeParts(catalog_unit_of_work))
    list_parts = ListParts(catalog_unit_of_work)

    async def sample_parts(workspace_id: WorkspaceId) -> dict[str, PartId]:
        """The bench's parts by name, one page (the sample is tiny). A bench that was just
        restored holds each sample name once, so a name is enough to find a part."""
        page = await list_parts(CatalogWorkspaceId(workspace_id), PartQuery())
        return {part.name.value: PartId(part.id) for part in page.items}

    try:
        yield RestoreSampleProjects(
            unit_of_work,
            SampleWrites(
                CreateProject(unit_of_work, clock, ids),
                UpdateRevision(unit_of_work, clock),
                ForkRevision(unit_of_work, clock, ids),
            ),
            SampleBoms(AddBomLine(unit_of_work, parts, clock, ids), sample_parts),
            ReserveRevision(build_unit_of_work),
        )
    finally:
        await engine.dispose()
