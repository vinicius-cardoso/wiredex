"""Projects over HTTP: the list and its tags, a project page, its revisions and their BOMs.

A factory, as the other routers are: the use cases and the workspace dependency come in as
arguments, so the composition root decides what runs. Projects never imports identity —
`bootstrap/app.py` builds `current_workspace` from the session use cases and hands it over
(design §HTTP API, the independence contract).
"""

from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from wiredex.projects.api.schemas import (
    BomLineRequest,
    BomLineResponse,
    BomRefusalResponse,
    BomResponse,
    CreateProjectRequest,
    DismantleRequest,
    LifecycleRefusalResponse,
    LifecycleResponse,
    NetlistResponse,
    NetRefusalResponse,
    NetRequest,
    NetResponse,
    NewRevisionRequest,
    PartHoldingResponse,
    PinUsageResponse,
    ProjectResponse,
    ProjectSummaryResponse,
    ProjectTagResponse,
    ReserveRequest,
    RevisionRefResponse,
    RevisionResponse,
    ShortRevisionsResponse,
    TiedUpPartsResponse,
    UpdateProjectRequest,
    UpdateRevisionRequest,
)
from wiredex.projects.application.bom import AddBomLine, GetBom, RemoveBomLine, UpdateBomLine
from wiredex.projects.application.dashboard import DEFAULT_LIMIT as DEFAULT_DASHBOARD_LIMIT
from wiredex.projects.application.dashboard import MAX_LIMIT as MAX_DASHBOARD_LIMIT
from wiredex.projects.application.dashboard import ListShortRevisions, ListTiedUpParts
from wiredex.projects.application.lifecycle import (
    MAX_REVISION_REFS,
    BuildRevision,
    CancelReservation,
    DismantleRevision,
    GetLifecycle,
    GetRevisionRef,
    GetRevisionRefs,
    ListPartHoldings,
    ReserveRevision,
)
from wiredex.projects.application.netlist import (
    AddNet,
    GetNetlist,
    GetPinUsage,
    RemoveNet,
    UpdateNet,
)
from wiredex.projects.application.ports import NewBomLine, NewRevision, ProjectView
from wiredex.projects.application.projects import (
    CreateProject,
    DeleteProject,
    GetProject,
    ListProjects,
    ListProjectTags,
    UpdateProject,
)
from wiredex.projects.application.revisions import (
    AddRevision,
    DeleteRevision,
    ForkRevision,
    GetRevision,
    UpdateRevision,
)
from wiredex.projects.domain.bom import BomNotes
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.errors import (
    BomLineNotFoundError,
    ContentError,
    DesignatorTakenError,
    DuplicateProjectNameError,
    DuplicateRevisionLabelError,
    LastRevisionError,
    NetError,
    NetNameTakenError,
    NetNotFoundError,
    NoLabelLeftError,
    PartNotFoundError,
    ProjectNotFoundError,
    ProjectsError,
    RevisionContentLockedError,
    RevisionHoldsStockError,
    RevisionNotFoundError,
)
from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.lifecycle import (
    LifecycleRefusal,
    RepeatedUnitError,
    TooManyUnitsError,
    UnitNotNeededError,
    UnknownLocationError,
    UnknownUnitError,
)
from wiredex.projects.domain.netlist import NetDraft
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.revision import RevisionDetails
from wiredex.projects.domain.values import (
    MAX_TAGS,
    BomLineId,
    Description,
    LocationId,
    NetId,
    Notes,
    PartId,
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    Summary,
    Tags,
    UnitId,
    WorkspaceId,
)


@dataclass(frozen=True, slots=True)
class ProjectsUseCases:
    create_project: CreateProject
    update_project: UpdateProject
    delete_project: DeleteProject
    get_project: GetProject
    list_projects: ListProjects
    list_project_tags: ListProjectTags
    add_revision: AddRevision
    fork_revision: ForkRevision
    update_revision: UpdateRevision
    delete_revision: DeleteRevision
    get_revision: GetRevision
    get_bom: GetBom
    add_bom_line: AddBomLine
    update_bom_line: UpdateBomLine
    remove_bom_line: RemoveBomLine
    reserve_revision: ReserveRevision
    cancel_reservation: CancelReservation
    build_revision: BuildRevision
    dismantle_revision: DismantleRevision
    get_lifecycle: GetLifecycle
    get_revision_ref: GetRevisionRef
    get_revision_refs: GetRevisionRefs
    list_part_holdings: ListPartHoldings
    get_netlist: GetNetlist
    add_net: AddNet
    update_net: UpdateNet
    remove_net: RemoveNet
    get_pin_usage: GetPinUsage
    list_tied_up_parts: ListTiedUpParts
    list_short_revisions: ListShortRevisions


type CurrentWorkspaceDependency = Callable[[Request], Awaitable[WorkspaceId]]

# The design's error table, leaf by leaf. Anything else a projects rule refuses — a name, a
# tag, a label, a summary or a text its value won't take — is the request's content being
# unprocessable, so 422. `RevisionHoldsStockError` answers a delete refused because the
# revision holds stock, and `RevisionContentLockedError` a BOM write to a revision that isn't
# a draft; both 409.
_STATUS_BY_ERROR: Mapping[type[ProjectsError], int] = {
    ProjectNotFoundError: status.HTTP_404_NOT_FOUND,
    RevisionNotFoundError: status.HTTP_404_NOT_FOUND,
    BomLineNotFoundError: status.HTTP_404_NOT_FOUND,
    NetNotFoundError: status.HTTP_404_NOT_FOUND,
    PartNotFoundError: status.HTTP_404_NOT_FOUND,
    NetNameTakenError: status.HTTP_409_CONFLICT,
    DuplicateProjectNameError: status.HTTP_409_CONFLICT,
    DuplicateRevisionLabelError: status.HTTP_409_CONFLICT,
    LastRevisionError: status.HTTP_409_CONFLICT,
    RevisionHoldsStockError: status.HTTP_409_CONFLICT,
    DesignatorTakenError: status.HTTP_409_CONFLICT,
    RevisionContentLockedError: status.HTTP_409_CONFLICT,
    NoLabelLeftError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    # A refused transition is 409 by default (transition_not_allowed, empty_bom, short,
    # unit_not_in_stock, stock_changed); the four named-unit refusals and an unknown location
    # are the request's content being unprocessable, so 422 (decision 14). The base entry
    # answers the 409s through the MRO walk `_status_of` does.
    LifecycleRefusal: status.HTTP_409_CONFLICT,
    UnknownUnitError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    RepeatedUnitError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    UnitNotNeededError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    TooManyUnitsError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    UnknownLocationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}
REFUSED = status.HTTP_422_UNPROCESSABLE_CONTENT


def create_router(
    use_cases: ProjectsUseCases, current_workspace: CurrentWorkspaceDependency
) -> APIRouter:
    router = APIRouter(prefix="/projects", tags=["projects"])
    # The revision routes first: FastAPI takes the first route whose path matches, so
    # `/projects/revisions/…` and `/projects/tags` have to be declared before
    # `/projects/{project_id}`, or they would reach it and fail as a UUID.
    _add_revision_routes(router, use_cases, current_workspace)
    _add_bom_routes(router, use_cases, current_workspace)
    _add_lifecycle_routes(router, use_cases, current_workspace)
    _add_netlist_routes(router, use_cases, current_workspace)
    _add_dashboard_routes(router, use_cases, current_workspace)
    _add_project_routes(router, use_cases, current_workspace)
    return router


type DashboardLimit = Annotated[int, Query(ge=1, le=MAX_DASHBOARD_LIMIT)]


def _add_dashboard_routes(
    router: APIRouter, use_cases: ProjectsUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """The dashboard's reads (18-dashboard). Static paths, declared before `/{project_id}` so
    neither reaches it as an id; reads only, so no CSRF. A limit outside 1 to 100 is FastAPI's
    own 422 (requirement 1.3)."""

    @router.get("/holdings")
    async def list_tied_up_parts(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        limit: DashboardLimit = DEFAULT_DASHBOARD_LIMIT,
    ) -> TiedUpPartsResponse:
        """The parts reserved or built revisions hold, the most tied up first, each with the
        revisions holding it, and how many more there are (requirements 1.1 to 1.4)."""
        parts = await use_cases.list_tied_up_parts(workspace_id, limit)
        return TiedUpPartsResponse.from_parts(parts)

    @router.get("/shortages")
    async def list_short_revisions(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        limit: DashboardLimit = DEFAULT_DASHBOARD_LIMIT,
    ) -> ShortRevisionsResponse:
        """The drafts whose BOM is short of a stocked part or names an unknown one, by project
        name and label, each with those parts, and how many more there are (2.1 to 2.4)."""
        revisions = await use_cases.list_short_revisions(workspace_id, limit)
        return ShortRevisionsResponse.from_revisions(revisions)


def _add_netlist_routes(
    router: APIRouter, use_cases: ProjectsUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """A revision's netlist, and its nets added, edited and removed (11-netlist-editor).

    A net is always named under its revision, so a net id sent under another revision is a 404
    (requirement 1.12). The writes declare `NetRefusalResponse` as their 409 and 422, which puts
    it and its codes into the OpenAPI schema for the web to translate (decision 12).
    """

    refused: dict[int | str, dict[str, Any]] = {
        status.HTTP_409_CONFLICT: {"model": NetRefusalResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": NetRefusalResponse},
    }

    @router.get("/revisions/{revision_id}/netlist")
    async def get_netlist(
        revision_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> NetlistResponse:
        """The nets oldest first, what each reference resolves to now, a summary, and the
        BOM's designators and pins the editor picks from (requirements 1.11, 4, 5.2, 7)."""
        with _refusals():
            view = await use_cases.get_netlist(workspace_id, RevisionId(revision_id))
        return NetlistResponse.from_view(view)

    @router.get("/parts/{part_id}/pin-usage")
    async def get_pin_usage(
        part_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> PinUsageResponse:
        """Each pin of the part in its saved order with the nets on it, in every revision of
        the workspace whatever its status, and the numbers the pinout doesn't hold
        (12-wiring-validation requirement 7). A part the workspace doesn't hold is a 404."""
        with _refusals():
            usage = await use_cases.get_pin_usage(workspace_id, PartId(part_id))
        return PinUsageResponse.from_usage(usage)

    @router.post(
        "/revisions/{revision_id}/netlist/nets",
        status_code=status.HTTP_201_CREATED,
        responses=refused,
    )
    async def add_net(
        revision_id: UUID,
        body: NetRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> NetResponse:
        """A net after the others; 422 for a reference that names no real pin, 409 for a
        name another net holds or a revision that isn't a draft (1.1, 1.3, 3, 5.1)."""
        with _refusals(), _net_refusals():
            written = await use_cases.add_net(
                workspace_id, RevisionId(revision_id), _net_draft(body)
            )
        return NetResponse.from_net(written.net, written.view)

    @router.patch("/revisions/{revision_id}/netlist/nets/{net_id}", responses=refused)
    async def update_net(
        revision_id: UUID,
        net_id: UUID,
        body: NetRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> NetResponse:
        """Replaces the net's name, color, notes and pins whole, keeping the references it
        already held as they are; a no-op writes nothing (requirements 1.9, 3.8)."""
        with _refusals(), _net_refusals():
            written = await use_cases.update_net(
                workspace_id, RevisionId(revision_id), NetId(net_id), _net_draft(body)
            )
        return NetResponse.from_net(written.net, written.view)

    @router.delete(
        "/revisions/{revision_id}/netlist/nets/{net_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=refused,
    )
    async def remove_net(
        revision_id: UUID,
        net_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """The net and its references, while the revision is a draft (1.10, 5.1)."""
        with _refusals(), _net_refusals():
            await use_cases.remove_net(workspace_id, RevisionId(revision_id), NetId(net_id))


def _net_draft(body: NetRequest) -> NetDraft:
    return NetDraft.parse(body.name, body.color, body.notes, body.pins)


def _add_project_routes(
    router: APIRouter, use_cases: ProjectsUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """The list, its tags and creating a project, then one project: open, edit and delete it.

    Split in two so each stays a small factory, as inventory's unit routes are, and in this
    order: `/tags` is declared before `/{project_id}` for the reason `create_router` gives.
    Every write is a POST, PATCH or DELETE, so it carries the CSRF header (ADR 0008), which
    the auth test covers.
    """
    _add_project_list_routes(router, use_cases, current_workspace)
    _add_one_project_routes(router, use_cases, current_workspace)


def _add_project_list_routes(
    router: APIRouter, use_cases: ProjectsUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """The list, creating a project, and the workspace's tags."""

    @router.get("")
    async def list_projects(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        q: Annotated[str | None, Query()] = None,
        tag: Annotated[list[str] | None, Query(max_length=MAX_TAGS)] = None,
    ) -> list[ProjectSummaryResponse]:
        """The projects, newest activity first, narrowed by a text in the name and by tags
        they all carry, each tag normalized as a stored one is (3.1 to 3.5)."""
        with _refusals():
            wanted = ProjectFilter(q, Tags.of(tag or ()))
            summaries = await use_cases.list_projects(workspace_id, wanted)
        return [ProjectSummaryResponse.from_summary(summary) for summary in summaries]

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def create_project(
        body: CreateProjectRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> ProjectResponse:
        """A new project with its revision A; 409 for a name another project holds (1.1, 1.3)."""
        with _refusals():
            details = _project_details(body.name, body.description, body.tags)
            view = await use_cases.create_project(workspace_id, details)
            return _project_response(view)

    @router.get("/tags")
    async def list_project_tags(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> list[ProjectTagResponse]:
        """Each tag the workspace's projects carry, with its count, alphabetical (2.6)."""
        counts = await use_cases.list_project_tags(workspace_id)
        return [ProjectTagResponse.from_count(count) for count in counts]


def _add_one_project_routes(
    router: APIRouter, use_cases: ProjectsUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """One project by its id: open, edit and delete it."""

    @router.get("/{project_id}")
    async def get_project(
        project_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> ProjectResponse:
        """A project page: its revisions, the latest and the next label (requirement 1.6)."""
        with _refusals():
            view = await use_cases.get_project(workspace_id, ProjectId(project_id))
            return _project_response(view)

    @router.patch("/{project_id}")
    async def update_project(
        project_id: UUID,
        body: UpdateProjectRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> ProjectResponse:
        """Replaces the name, description and tags whole; a no-op writes nothing (1.5)."""
        with _refusals():
            details = _project_details(body.name, body.description, body.tags)
            view = await use_cases.update_project(workspace_id, ProjectId(project_id), details)
            return _project_response(view)

    @router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_project(
        project_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """Moves the project and its revisions to the trash, where `/api/trash` restores or
        deletes them for good; 409 while one of them isn't a draft (1.7, 1.8; 16's 1.1)."""
        with _refusals():
            await use_cases.delete_project(workspace_id, ProjectId(project_id))


def _add_revision_routes(
    router: APIRouter, use_cases: ProjectsUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """Add a revision to a project, then edit, delete and fork one by its own id.

    A revision is named by its id alone, under `/projects/revisions/…`, because a revision's
    id is enough to find its project and the web links to one from anywhere (design's HTTP
    API).
    """

    @router.post("/{project_id}/revisions", status_code=status.HTTP_201_CREATED)
    async def add_revision(
        project_id: UUID,
        body: NewRevisionRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> RevisionResponse:
        """A new draft, labelled as given or suggested; 409 for a label taken (4.1, 4.3)."""
        with _refusals():
            revision = await use_cases.add_revision(
                workspace_id, ProjectId(project_id), _new_revision(body)
            )
        return RevisionResponse.from_revision(revision)

    @router.patch("/revisions/{revision_id}")
    async def update_revision(
        revision_id: UUID,
        body: UpdateRevisionRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> RevisionResponse:
        """Replaces the label, summary and notes whole, in any status (requirement 4.8)."""
        with _refusals():
            details = RevisionDetails(
                RevisionLabel(body.label), _summary(body.summary), _notes(body.notes)
            )
            revision = await use_cases.update_revision(
                workspace_id, RevisionId(revision_id), details
            )
        return RevisionResponse.from_revision(revision)

    @router.delete("/revisions/{revision_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_revision(
        revision_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """A draft revision of a project that keeps another; 409 otherwise (5.1 to 5.3)."""
        with _refusals():
            await use_cases.delete_revision(workspace_id, RevisionId(revision_id))

    @router.post("/revisions/{revision_id}/fork", status_code=status.HTTP_201_CREATED)
    async def fork_revision(
        revision_id: UUID,
        body: NewRevisionRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> RevisionResponse:
        """A draft of the same project started from this one, whatever its status (6.1)."""
        with _refusals():
            fork = await use_cases.fork_revision(
                workspace_id, RevisionId(revision_id), _new_revision(body)
            )
        return RevisionResponse.from_revision(fork)


def _add_bom_routes(
    router: APIRouter, use_cases: ProjectsUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """A revision's BOM, and its lines added, edited and removed.

    A line is always named under its revision, so a line id sent under another revision is a
    404 (requirement 4.12). The writes declare `BomRefusalResponse` as their 409, which puts
    it and its codes into the OpenAPI schema: the web types its sentences against the
    generated codes, so none ships untranslated (design's HTTP API).
    """

    refused: dict[int | str, dict[str, Any]] = {
        status.HTTP_409_CONFLICT: {"model": BomRefusalResponse}
    }

    @router.get("/revisions/{revision_id}/bom")
    async def get_bom(
        revision_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> BomResponse:
        """The lines oldest first, the shortage report as stock stands now, and whether the
        BOM can change (requirements 4.11, 5.2, 6.1, 6.7)."""
        with _refusals():
            view = await use_cases.get_bom(workspace_id, RevisionId(revision_id))
        return BomResponse.from_view(view)

    @router.post(
        "/revisions/{revision_id}/bom/lines",
        status_code=status.HTTP_201_CREATED,
        responses=refused,
    )
    async def add_bom_line(
        revision_id: UUID,
        body: BomLineRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> BomLineResponse:
        """A line after the others; 409 for a designator another line holds, or a revision
        that isn't a draft (requirements 4.1, 4.6, 5.1)."""
        with _refusals(), _bom_refusals():
            line = await use_cases.add_bom_line(
                workspace_id, RevisionId(revision_id), _new_bom_line(body)
            )
        return BomLineResponse.from_line(line)

    @router.patch("/revisions/{revision_id}/bom/lines/{line_id}", responses=refused)
    async def update_bom_line(
        revision_id: UUID,
        line_id: UUID,
        body: BomLineRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> BomLineResponse:
        """Replaces the line's part, designators, quantity and notes whole; a no-op writes
        nothing (requirement 4.9)."""
        with _refusals(), _bom_refusals():
            line = await use_cases.update_bom_line(
                workspace_id, RevisionId(revision_id), BomLineId(line_id), _new_bom_line(body)
            )
        return BomLineResponse.from_line(line)

    @router.delete(
        "/revisions/{revision_id}/bom/lines/{line_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=refused,
    )
    async def remove_bom_line(
        revision_id: UUID,
        line_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """The line and its designators, while the revision is a draft (4.10, 5.1)."""
        with _refusals(), _bom_refusals():
            await use_cases.remove_bom_line(
                workspace_id, RevisionId(revision_id), BomLineId(line_id)
            )


def _add_lifecycle_routes(
    router: APIRouter, use_cases: ProjectsUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """The four transitions, the lifecycle read, a revision by its id alone, and a part's
    holdings (decision 13).

    A revision is named by its id, under `/projects/revisions/…`, as its other routes are; a
    part's holdings by the part's id, under `/projects/parts/…`, both declared before
    `/{project_id}` for the reason `create_router` gives. Split in two so each stays a small
    factory, as the project routes are.
    """
    _add_transition_routes(router, use_cases, current_workspace)
    _add_lifecycle_read_routes(router, use_cases, current_workspace)


def _add_transition_routes(
    router: APIRouter, use_cases: ProjectsUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """The four transitions, each a POST that carries the CSRF header (ADR 0008), which the
    auth test covers. They declare `LifecycleRefusalResponse` as their 409 and 422, so its
    shape and codes reach the OpenAPI schema and the web types its sentences against them
    (design's HTTP API)."""
    refused: dict[int | str, dict[str, Any]] = {
        status.HTTP_409_CONFLICT: {"model": LifecycleRefusalResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": LifecycleRefusalResponse},
    }

    @router.post("/revisions/{revision_id}/reserve", responses=refused)
    async def reserve_revision(
        revision_id: UUID,
        body: ReserveRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> RevisionResponse:
        """A draft revision's parts set aside, or its shortages reported; 409 or 422 with the
        refusal (requirement 2)."""
        with _refusals(), _lifecycle_refusals():
            revision = await use_cases.reserve_revision(
                workspace_id, RevisionId(revision_id), [UnitId(unit) for unit in body.units]
            )
        return RevisionResponse.from_revision(revision)

    @router.post("/revisions/{revision_id}/cancel", responses=refused)
    async def cancel_reservation(
        revision_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> RevisionResponse:
        """A reserved revision cancelled back to draft, its stock released (requirement 4)."""
        with _refusals(), _lifecycle_refusals():
            revision = await use_cases.cancel_reservation(workspace_id, RevisionId(revision_id))
        return RevisionResponse.from_revision(revision)

    @router.post("/revisions/{revision_id}/build", responses=refused)
    async def build_revision(
        revision_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> RevisionResponse:
        """A reserved revision built, its reservation consumed (requirement 5)."""
        with _refusals(), _lifecycle_refusals():
            revision = await use_cases.build_revision(workspace_id, RevisionId(revision_id))
        return RevisionResponse.from_revision(revision)

    @router.post("/revisions/{revision_id}/dismantle", responses=refused)
    async def dismantle_revision(
        revision_id: UUID,
        body: DismantleRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> RevisionResponse:
        """A built revision dismantled, its parts returned to the chosen location; 422 for a
        location the workspace doesn't hold (requirement 6)."""
        with _refusals(), _lifecycle_refusals():
            revision = await use_cases.dismantle_revision(
                workspace_id, RevisionId(revision_id), LocationId(body.location_id)
            )
        return RevisionResponse.from_revision(revision)


def _add_lifecycle_read_routes(
    router: APIRouter, use_cases: ProjectsUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """The lifecycle read, a revision by its id alone, and a part's holdings. Reads only, so
    no CSRF; a revision or part of another workspace is simply not found (requirement 11.3)."""

    @router.get("/revisions/{revision_id}/lifecycle")
    async def get_lifecycle(
        revision_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> LifecycleResponse:
        """A revision's build: its status, the transitions it allows, whether it can be
        deleted, and each part it holds (requirement 10.1)."""
        with _refusals():
            lifecycle = await use_cases.get_lifecycle(workspace_id, RevisionId(revision_id))
        return LifecycleResponse.from_lifecycle(lifecycle)

    @router.get("/revisions")
    async def get_revision_refs(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        revision_id: Annotated[list[UUID], Query(min_length=1, max_length=MAX_REVISION_REFS)],
    ) -> list[RevisionRefResponse]:
        """Several revisions found by their ids alone, in one read, in the order asked: what
        a list naming the build beside each row asks (the boards list). An id the workspace
        doesn't hold is left out; more than 200 ids, or none, is a 422."""
        refs = await use_cases.get_revision_refs(
            workspace_id, [RevisionId(revision) for revision in revision_id]
        )
        return [RevisionRefResponse.from_ref(ref) for ref in refs]

    @router.get("/revisions/{revision_id}")
    async def get_revision_ref(
        revision_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> RevisionRefResponse:
        """A revision found by its id alone: its label, summary, status and project (10.2)."""
        with _refusals():
            ref = await use_cases.get_revision_ref(workspace_id, RevisionId(revision_id))
        return RevisionRefResponse.from_ref(ref)

    @router.get("/parts/{part_id}/holdings")
    async def list_part_holdings(
        part_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> list[PartHoldingResponse]:
        """Each revision holding the part, with how many it reserves and consumed (10.4)."""
        with _refusals():
            views = await use_cases.list_part_holdings(workspace_id, PartId(part_id))
        return [PartHoldingResponse.from_view(view) for view in views]


@contextmanager
def _refusals() -> Iterator[None]:
    """Turns a projects refusal into the status the design's table gives it.

    One place rather than a handler full of `except` clauses, and no global handler: the
    mapping is part of this router's contract, not the application's, as catalog's is.
    """
    try:
        yield
    except ProjectsError as error:
        raise HTTPException(_status_of(error), str(error)) from error


@contextmanager
def _bom_refusals() -> Iterator[None]:
    """A refused line write, answered with its code, field and item instead of a sentence.

    Nested inside `_refusals()` and never outside it, as catalog's `_refused_rows()` is: a
    `ContentError` is a `ProjectsError` too, so the structured detail has to be built first,
    or the generic mapping would flatten it to a message and the editor would have no field
    to mark. A missing revision or line falls through to that mapping as a plain 404.
    """
    try:
        yield
    except ContentError as error:
        refusal = BomRefusalResponse.from_error(error)
        raise HTTPException(_status_of(error), refusal.model_dump(mode="json")) from error


@contextmanager
def _lifecycle_refusals() -> Iterator[None]:
    """A refused transition, answered with its code, transition and fields instead of a plain
    sentence (decision 14).

    Nested inside `_refusals()` and never outside it, as `_bom_refusals()` is: a
    `LifecycleRefusal` is a `ProjectsError` too, so its structured detail is built here before
    the generic mapping would flatten it to a message. The status still comes from the error
    table `_status_of` reads, so the four unit codes stay 422 and the rest 409 (design's error
    table). A missing revision falls through to that mapping as a plain 404.
    """
    try:
        yield
    except LifecycleRefusal as error:
        refusal = LifecycleRefusalResponse.from_refusal(error)
        raise HTTPException(_status_of(error), refusal.model_dump(mode="json")) from error


@contextmanager
def _net_refusals() -> Iterator[None]:
    """A refused net write, answered with its code, field and item instead of a sentence.

    Nested inside `_refusals()` and never outside it, as `_bom_refusals()` is. A revision that
    isn't a draft is refused by 09's `RevisionContentLockedError`, which is the BOM's family,
    so it is answered here in the netlist's words too. A missing revision or net falls through
    to the generic mapping as a plain 404.
    """
    try:
        yield
    except NetError as error:
        refusal = NetRefusalResponse.from_error(error)
        raise HTTPException(_status_of(error), refusal.model_dump(mode="json")) from error
    except RevisionContentLockedError as error:
        refusal = NetRefusalResponse.locked(error)
        raise HTTPException(_status_of(error), refusal.model_dump(mode="json")) from error


def _status_of(error: ProjectsError) -> int:
    for kind in type(error).__mro__:
        found = _STATUS_BY_ERROR.get(kind)
        if found is not None:
            return found
    return REFUSED


def _project_response(view: ProjectView) -> ProjectResponse:
    """The page, or a 404 for a project whose revisions went while it was read: only deleting
    the project takes its last one (decision 2), as `ListProjects` reasons too."""
    latest = view.revisions.latest
    if latest is None:
        raise ProjectNotFoundError("that project doesn't exist")
    return ProjectResponse.from_view(view, latest)


def _project_details(name: str, description: str | None, tags: list[str]) -> ProjectDetails:
    return ProjectDetails(ProjectName(name), _description(description), Tags.of(tags))


def _new_revision(body: NewRevisionRequest) -> NewRevision:
    return NewRevision(
        label=None if body.label is None else RevisionLabel(body.label),
        summary=_summary(body.summary),
        notes=_notes(body.notes),
    )


def _new_bom_line(body: BomLineRequest) -> NewBomLine:
    """The line as typed: designators read from their list, blank notes as none (4.5)."""
    notes = _given(body.notes)
    return NewBomLine(
        part_id=PartId(body.part_id),
        designators=Designators.parse(body.designators),
        quantity=body.quantity,
        notes=None if notes is None else BomNotes(notes),
    )


def _given(text: str | None) -> str | None:
    """Blank text is nothing given (design's HTTP API): a cleared field means no description,
    no summary or no notes, never a refusal for being empty."""
    return text if text is not None and text.strip() else None


def _description(text: str | None) -> Description | None:
    given = _given(text)
    return None if given is None else Description(given)


def _summary(text: str | None) -> Summary | None:
    given = _given(text)
    return None if given is None else Summary(given)


def _notes(text: str | None) -> Notes | None:
    given = _given(text)
    return None if given is None else Notes(given)
