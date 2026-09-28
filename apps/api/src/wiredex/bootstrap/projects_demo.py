"""Wiring for the projects part of `wiredex demo reset` and `wiredex demo invite`.

Kept out of `bootstrap/projects.py` on purpose, as `inventory_demo.py` is kept out of
`bootstrap/inventory.py`: this is only the demo's wiring, over an engine of its own for one
run of the command (ADR 0011).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Settings
from wiredex.projects.application.demo import RestoreSampleProjects
from wiredex.projects.application.projects import CreateProject
from wiredex.projects.application.revisions import ForkRevision, UpdateRevision
from wiredex.projects.domain.values import WorkspaceId
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

    try:
        yield RestoreSampleProjects(
            unit_of_work,
            CreateProject(unit_of_work, clock, ids),
            UpdateRevision(unit_of_work, clock),
            ForkRevision(unit_of_work, clock, ids),
        )
    finally:
        await engine.dispose()
