"""Projects over HTTP: the list and its tags, a project page, and its revisions.

A factory, as the other routers are: the use cases and the workspace dependency come in as
arguments, so the composition root decides what runs. Projects never imports identity —
`bootstrap/app.py` builds `current_workspace` from the session use cases and hands it over
(design §HTTP API, the independence contract).
"""

from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from wiredex.projects.api.schemas import (
    CreateProjectRequest,
    NewRevisionRequest,
    ProjectResponse,
    ProjectSummaryResponse,
    ProjectTagResponse,
    RevisionResponse,
    UpdateProjectRequest,
    UpdateRevisionRequest,
)
from wiredex.projects.application.ports import NewRevision, ProjectView
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
from wiredex.projects.domain.errors import (
    DuplicateProjectNameError,
    DuplicateRevisionLabelError,
    LastRevisionError,
    NoLabelLeftError,
    ProjectNotFoundError,
    ProjectsError,
    RevisionInUseError,
    RevisionNotFoundError,
)
from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.revision import RevisionDetails
from wiredex.projects.domain.values import (
    MAX_TAGS,
    Description,
    Notes,
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    Summary,
    Tags,
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


type CurrentWorkspaceDependency = Callable[[Request], Awaitable[WorkspaceId]]

# The design's error table, leaf by leaf. Anything else a projects rule refuses — a name, a
# tag, a label, a summary or a text its value won't take — is the request's content being
# unprocessable, so 422. `RevisionInUseError` can't be reached before 10-build-lifecycle
# moves a status, and is mapped now so 10 doesn't touch this router.
_STATUS_BY_ERROR: Mapping[type[ProjectsError], int] = {
    ProjectNotFoundError: status.HTTP_404_NOT_FOUND,
    RevisionNotFoundError: status.HTTP_404_NOT_FOUND,
    DuplicateProjectNameError: status.HTTP_409_CONFLICT,
    DuplicateRevisionLabelError: status.HTTP_409_CONFLICT,
    LastRevisionError: status.HTTP_409_CONFLICT,
    RevisionInUseError: status.HTTP_409_CONFLICT,
    NoLabelLeftError: status.HTTP_422_UNPROCESSABLE_CONTENT,
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
    _add_project_routes(router, use_cases, current_workspace)
    return router


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
        """The project and its revisions; 409 while one of them isn't a draft (1.7, 1.8)."""
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
