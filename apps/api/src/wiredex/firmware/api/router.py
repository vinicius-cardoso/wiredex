"""Firmware over HTTP: the list, a firmware's page, the revisions it runs on, its versions and
their source files (13-firmware-versions, HTTP), and the flash log (15-flash-log, HTTP).

A factory, as the other routers are: the use cases and the workspace dependency come in as
arguments, so the composition root decides what runs. Firmware never imports identity,
projects or inventory: `bootstrap/app.py` builds `current_workspace` from the session use cases
and hands it over, and `bootstrap/firmware.py` binds projects' revisions and inventory's units
to firmware's session (decision 5; 15's decision 8). Every write is a POST, PATCH, PUT or
DELETE, so a cookie session carries the CSRF header for it (ADR 0008), which the auth test
covers.
"""

from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse

from wiredex.firmware.api.schemas import (
    BoardResponse,
    FirmwareRefusalResponse,
    FirmwareRequest,
    FirmwareResponse,
    FirmwareSummaryResponse,
    FirmwareVersionResponse,
    FlashRequest,
    FlashResponse,
    NewFirmwareRequest,
    NewSourceFilesRequest,
    NewVersionRequest,
    SourceFileRequest,
    SourceFileResponse,
    UnitFirmwareResponse,
    VersionRequest,
)
from wiredex.firmware.application.firmware import (
    CreateFirmware,
    DeleteFirmware,
    GetFirmware,
    ListFirmware,
    ListRevisionFirmware,
    UpdateFirmware,
)
from wiredex.firmware.application.flashes import (
    GetUnitFirmware,
    ListBoards,
    LogFlash,
    RemoveFlash,
)
from wiredex.firmware.application.links import LinkRevision, UnlinkRevision
from wiredex.firmware.application.ports import NewFlash, NewSourceFile
from wiredex.firmware.application.sources import (
    AddSourceFiles,
    RemoveSourceFile,
    UpdateSourceFile,
)
from wiredex.firmware.application.versions import (
    DeleteVersion,
    GetVersion,
    ReleaseVersion,
    StartVersion,
    UpdateVersion,
)
from wiredex.firmware.domain.errors import (
    FirmwareError,
    FirmwareFlashedError,
    FirmwareNotFoundError,
    FirmwareRefusalError,
    FlashNotFoundError,
    NameInTrashError,
    NameTakenError,
    NoChangelogError,
    NoFilesError,
    NotReleasedError,
    PathTakenError,
    RevisionNotFoundError,
    SourceFileNotFoundError,
    UnitNotFoundError,
    UnitRetiredError,
    VersionFlashedError,
    VersionNotFoundError,
    VersionReleasedError,
    VersionTakenError,
)
from wiredex.firmware.domain.firmware import FirmwareDetails
from wiredex.firmware.domain.flash import FlashNotes
from wiredex.firmware.domain.semver import SemVer
from wiredex.firmware.domain.values import (
    BoardTarget,
    Changelog,
    Description,
    FirmwareId,
    FirmwareName,
    FlashId,
    Framework,
    RevisionId,
    SourceFileId,
    UnitId,
    VersionId,
    WorkspaceId,
)


@dataclass(frozen=True, slots=True)
class FirmwareUseCases:
    create_firmware: CreateFirmware
    update_firmware: UpdateFirmware
    delete_firmware: DeleteFirmware
    get_firmware: GetFirmware
    list_firmware: ListFirmware
    list_revision_firmware: ListRevisionFirmware
    link_revision: LinkRevision
    unlink_revision: UnlinkRevision
    start_version: StartVersion
    update_version: UpdateVersion
    release_version: ReleaseVersion
    delete_version: DeleteVersion
    get_version: GetVersion
    add_source_files: AddSourceFiles
    update_source_file: UpdateSourceFile
    remove_source_file: RemoveSourceFile
    log_flash: LogFlash
    get_unit_firmware: GetUnitFirmware
    remove_flash: RemoveFlash
    list_boards: ListBoards


type CurrentWorkspaceDependency = Callable[[Request], Awaitable[WorkspaceId]]

# The design's Error Handling, leaf by leaf. Anything else a firmware rule refuses (a name, a
# target, a description, a number, a changelog, a path or a text its value won't take, a
# version's limits, and a flash's notes or a time too far ahead) is the request's content being
# unprocessable, so 422. A 409 is a request that was fine, refused by what the workspace already
# holds: a name, number or path taken, a version whose state won't allow it, a retired unit, or
# a version or firmware a board's log still names.
_STATUS_BY_ERROR: Mapping[type[FirmwareError], int] = {
    FirmwareNotFoundError: status.HTTP_404_NOT_FOUND,
    VersionNotFoundError: status.HTTP_404_NOT_FOUND,
    SourceFileNotFoundError: status.HTTP_404_NOT_FOUND,
    RevisionNotFoundError: status.HTTP_404_NOT_FOUND,
    UnitNotFoundError: status.HTTP_404_NOT_FOUND,
    FlashNotFoundError: status.HTTP_404_NOT_FOUND,
    NameTakenError: status.HTTP_409_CONFLICT,
    NameInTrashError: status.HTTP_409_CONFLICT,
    VersionTakenError: status.HTTP_409_CONFLICT,
    PathTakenError: status.HTTP_409_CONFLICT,
    VersionReleasedError: status.HTTP_409_CONFLICT,
    NoFilesError: status.HTTP_409_CONFLICT,
    NoChangelogError: status.HTTP_409_CONFLICT,
    NotReleasedError: status.HTTP_409_CONFLICT,
    UnitRetiredError: status.HTTP_409_CONFLICT,
    VersionFlashedError: status.HTTP_409_CONFLICT,
    FirmwareFlashedError: status.HTTP_409_CONFLICT,
}
REFUSED = status.HTTP_422_UNPROCESSABLE_CONTENT

# What a refused write answers, declared so `FirmwareRefusalResponse` and its codes reach the
# OpenAPI schema and the web types its sentences against them (decision 13). A write that can
# only be refused by the version's state, or by the flashes naming what it deletes, declares the
# 409 alone, and keeps FastAPI's own 422.
_REFUSAL_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {"model": FirmwareRefusalResponse},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": FirmwareRefusalResponse},
}
_CONFLICT_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {"model": FirmwareRefusalResponse},
}


# What keeps a file's text a text: see `get_raw_source_file`.
_RAW_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "Cache-Control": "private, no-store",
}


def create_router(
    use_cases: FirmwareUseCases, current_workspace: CurrentWorkspaceDependency
) -> APIRouter:
    router = APIRouter(prefix="/firmware", tags=["firmware"])
    # The static paths first, as projects' are: `/firmware/revisions/…`, `/firmware/versions/…`,
    # `/firmware/units/…` and `/firmware/flashes/…` are declared before
    # `/firmware/{firmware_id}`, so none of them reaches it as a UUID.
    _add_list_routes(router, use_cases, current_workspace)
    _add_version_routes(router, use_cases, current_workspace)
    _add_file_routes(router, use_cases, current_workspace)
    _add_flash_routes(router, use_cases, current_workspace)
    _add_firmware_routes(router, use_cases, current_workspace)
    _add_link_routes(router, use_cases, current_workspace)
    return router


def _add_list_routes(
    router: APIRouter, use_cases: FirmwareUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """The list, creating a firmware, and the firmware a revision runs."""

    @router.get("")
    async def list_firmware(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        search: Annotated[str | None, Query()] = None,
    ) -> list[FirmwareSummaryResponse]:
        """The firmware, last changed first, narrowed by a text in the name or the target
        (requirements 2.1 to 2.4)."""
        summaries = await use_cases.list_firmware(workspace_id, search)
        return [FirmwareSummaryResponse.from_summary(summary) for summary in summaries]

    @router.post("", status_code=status.HTTP_201_CREATED, responses=_REFUSAL_RESPONSES)
    async def create_firmware(
        body: NewFirmwareRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> FirmwareResponse:
        """A firmware with no versions, linked to the revision it is created for; 404 for a
        revision the workspace doesn't hold, 409 for a name another firmware holds (1.1, 1.3,
        3.3, 3.7)."""
        revision_id = None if body.revision_id is None else RevisionId(body.revision_id)
        with _refusals(), _firmware_refusals():
            view = await use_cases.create_firmware(workspace_id, _details(body), revision_id)
        return FirmwareResponse.from_view(view)

    @router.get("/revisions/{revision_id}")
    async def list_revision_firmware(
        revision_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> list[FirmwareSummaryResponse]:
        """The firmware a revision runs, by name; 404 for a revision the workspace doesn't
        hold, another bench's included (requirements 3.4, 3.7, 9.2)."""
        with _refusals():
            summaries = await use_cases.list_revision_firmware(
                workspace_id, RevisionId(revision_id)
            )
        return [FirmwareSummaryResponse.from_summary(summary) for summary in summaries]


def _add_version_routes(
    router: APIRouter, use_cases: FirmwareUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """A version by its id alone: open it, edit a draft, release it and delete it.

    A version is named by its id under `/firmware/versions/…`, because its id is enough to find
    its firmware and the web links to one from anywhere, as projects' revisions are.
    """

    @router.get("/versions/{version_id}")
    async def get_version(
        version_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> FirmwareVersionResponse:
        """A version with its base, its files with their text, and its limits (5.8)."""
        with _refusals():
            view = await use_cases.get_version(workspace_id, VersionId(version_id))
        return FirmwareVersionResponse.from_view(view)

    @router.patch("/versions/{version_id}", responses=_REFUSAL_RESPONSES)
    async def update_version(
        version_id: UUID,
        body: VersionRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> FirmwareVersionResponse:
        """Replaces a draft's number and changelog whole; a no-op writes nothing; 409 for a
        number another version holds or a released version (5.2, 5.7, 6.4)."""
        with _refusals(), _firmware_refusals():
            view = await use_cases.update_version(
                workspace_id,
                VersionId(version_id),
                SemVer.parse(body.version),
                _changelog(body.changelog),
            )
        return FirmwareVersionResponse.from_view(view)

    @router.post("/versions/{version_id}/release", responses=_CONFLICT_RESPONSES)
    async def release_version(
        version_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> FirmwareVersionResponse:
        """A draft released for good; 409 for one with no file or no changelog, or one already
        released (requirements 6.1 to 6.3, 6.5)."""
        with _refusals(), _firmware_refusals():
            view = await use_cases.release_version(workspace_id, VersionId(version_id))
        return FirmwareVersionResponse.from_view(view)

    @router.delete(
        "/versions/{version_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=_CONFLICT_RESPONSES,
    )
    async def delete_version(
        version_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """A version with its files, draft or released; the versions started from it keep
        going, their base cleared (requirement 8). 409 while a flash names it, listing those
        flashes (15's requirement 5.1)."""
        with _refusals(), _firmware_refusals():
            await use_cases.delete_version(workspace_id, VersionId(version_id))


def _add_file_routes(
    router: APIRouter, use_cases: FirmwareUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """A draft's files: a batch added, one edited, one removed (decision 10).

    A file is always named under its version, so a file id sent under another version is a 404
    (requirement 7.11).
    """

    @router.get(
        "/versions/{version_id}/files/{file_id}/raw",
        response_class=PlainTextResponse,
        responses={404: {"description": "No such version or file in this workspace."}},
    )
    async def get_raw_source_file(
        version_id: UUID,
        file_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> PlainTextResponse:
        """One file's text and nothing else, as `text/plain`, for a tab of its own.

        It is the owner's text served from the app's own origin, so the answer may never be
        read as a page: the type is not to be sniffed, and a sandboxing policy keeps a browser
        that renders it anyway from running anything in it. Never cached by a proxy, since it
        is private to the workspace.
        """
        with _refusals():
            view = await use_cases.get_version(workspace_id, VersionId(version_id))
        file = view.files.get(SourceFileId(file_id))
        if file is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "that file isn't in this version")
        return PlainTextResponse(file.text.value, headers=_RAW_HEADERS)

    @router.post(
        "/versions/{version_id}/files",
        status_code=status.HTTP_201_CREATED,
        responses=_REFUSAL_RESPONSES,
    )
    async def add_source_files(
        version_id: UUID,
        body: NewSourceFilesRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> list[SourceFileResponse]:
        """1 to 100 files beside the draft's others, all of them or none, answered in the
        version's order (requirements 7.1 to 7.7, 7.10)."""
        files = [_new_file(file) for file in body.files]
        with _refusals(), _firmware_refusals():
            added = await use_cases.add_source_files(workspace_id, VersionId(version_id), files)
        return [SourceFileResponse.from_file(file) for file in added]

    @router.patch("/versions/{version_id}/files/{file_id}", responses=_REFUSAL_RESPONSES)
    async def update_source_file(
        version_id: UUID,
        file_id: UUID,
        body: SourceFileRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> SourceFileResponse:
        """Replaces a draft's file's path and text whole under its id, so a rename keeps it; a
        no-op writes nothing (requirement 7.8)."""
        with _refusals(), _firmware_refusals():
            file = await use_cases.update_source_file(
                workspace_id, VersionId(version_id), SourceFileId(file_id), _new_file(body)
            )
        return SourceFileResponse.from_file(file)

    @router.delete(
        "/versions/{version_id}/files/{file_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=_CONFLICT_RESPONSES,
    )
    async def remove_source_file(
        version_id: UUID,
        file_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """One of a draft's files; 409 once the version is released (7.9, 6.4)."""
        with _refusals(), _firmware_refusals():
            await use_cases.remove_source_file(
                workspace_id, VersionId(version_id), SourceFileId(file_id)
            )


def _add_flash_routes(
    router: APIRouter, use_cases: FirmwareUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """The flash log (15-flash-log decision 13): what a board runs, a flash logged on it, an
    entry removed, and the boards a firmware runs on.

    A unit is inventory's, so its log is named under `/firmware/units/…` by the unit's id, and
    an entry under `/firmware/flashes/…` by its own: removing one needs neither its unit, which
    may be gone, nor its version (requirement 3.1).
    """

    @router.get("/units/{unit_id}")
    async def get_unit_firmware(
        unit_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> UnitFirmwareResponse:
        """A unit's flash log newest first, its current version and that firmware's newer
        release; a retired unit's too, saying so; 404 for a unit the workspace doesn't hold
        (requirements 2.1 to 2.5)."""
        with _refusals():
            view = await use_cases.get_unit_firmware(workspace_id, UnitId(unit_id))
        return UnitFirmwareResponse.from_view(view)

    @router.post(
        "/units/{unit_id}/flashes",
        status_code=status.HTTP_201_CREATED,
        responses=_REFUSAL_RESPONSES,
    )
    async def log_flash(
        unit_id: UUID,
        body: FlashRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> FlashResponse:
        """A released version flashed onto the unit, at the time given or now; 404 for a unit
        or version the workspace doesn't hold, 409 for a draft or a retired unit, 422 for a
        time more than five minutes ahead or notes the log won't take (requirement 1)."""
        with _refusals(), _firmware_refusals():
            view = await use_cases.log_flash(workspace_id, UnitId(unit_id), _new_flash(body))
        return FlashResponse.from_view(view)

    @router.delete("/flashes/{flash_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def remove_flash(
        flash_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """An entry removed from its unit's log, whatever the unit's status, a deleted unit's
        included; 404 for a flash the workspace doesn't hold (requirement 3)."""
        with _refusals():
            await use_cases.remove_flash(workspace_id, FlashId(flash_id))

    @router.get("/{firmware_id}/boards")
    async def list_boards(
        firmware_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> list[BoardResponse]:
        """The units whose current version is one of the firmware's, by code, retired and
        deleted ones left out; 404 for a firmware the workspace doesn't hold (requirement
        4)."""
        with _refusals():
            boards = await use_cases.list_boards(workspace_id, FirmwareId(firmware_id))
        return [BoardResponse.from_view(board) for board in boards]


def _add_firmware_routes(
    router: APIRouter, use_cases: FirmwareUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """One firmware by its id: open, edit and delete it, and start a version of it."""

    @router.get("/{firmware_id}")
    async def get_firmware(
        firmware_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> FirmwareResponse:
        """A firmware's page: the revisions it runs on, its versions, its latest release and
        its suggested version (requirement 1.8)."""
        with _refusals():
            view = await use_cases.get_firmware(workspace_id, FirmwareId(firmware_id))
        return FirmwareResponse.from_view(view)

    @router.patch("/{firmware_id}", responses=_REFUSAL_RESPONSES)
    async def update_firmware(
        firmware_id: UUID,
        body: FirmwareRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> FirmwareResponse:
        """Replaces the name, target, framework and description whole; a no-op writes nothing
        (requirement 1.7)."""
        with _refusals(), _firmware_refusals():
            view = await use_cases.update_firmware(
                workspace_id, FirmwareId(firmware_id), _details(body)
            )
        return FirmwareResponse.from_view(view)

    @router.delete(
        "/{firmware_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_CONFLICT_RESPONSES
    )
    async def delete_firmware(
        firmware_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """Moves the firmware to the trash with its versions, their files and its links, where
        `/api/trash` restores or deletes them for good (requirement 1.9; 16's 1.1). 409 while a
        flash names one of its versions, listing those flashes (15's requirement 5.2)."""
        with _refusals(), _firmware_refusals():
            await use_cases.delete_firmware(workspace_id, FirmwareId(firmware_id))

    @router.post(
        "/{firmware_id}/versions", status_code=status.HTTP_201_CREATED, responses=_REFUSAL_RESPONSES
    )
    async def start_version(
        firmware_id: UUID,
        body: NewVersionRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> FirmwareVersionResponse:
        """A new draft, numbered as typed or suggested, empty or holding a copy of a version of
        the same firmware; 404 for a version of another (requirements 5.4, 5.5, 5.9)."""
        base_id = None if body.from_version_id is None else VersionId(body.from_version_id)
        with _refusals(), _firmware_refusals():
            number = None if body.version is None else SemVer.parse(body.version)
            view = await use_cases.start_version(
                workspace_id, FirmwareId(firmware_id), number, base_id
            )
        return FirmwareVersionResponse.from_view(view)


def _add_link_routes(
    router: APIRouter, use_cases: FirmwareUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """The revisions a firmware runs on: a link made and removed, whatever the revision's
    status (decision 2). Both are idempotent, so the web can send either again safely."""

    @router.put("/{firmware_id}/revisions/{revision_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def link_revision(
        firmware_id: UUID,
        revision_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """Records that the firmware runs on the revision, and writes nothing when it already
        does; 404 for a revision the workspace doesn't hold (requirements 3.1, 3.7)."""
        with _refusals():
            await use_cases.link_revision(
                workspace_id, FirmwareId(firmware_id), RevisionId(revision_id)
            )

    @router.delete("/{firmware_id}/revisions/{revision_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def unlink_revision(
        firmware_id: UUID,
        revision_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """Removes the link, and answers success when there was none (requirement 3.2)."""
        with _refusals():
            await use_cases.unlink_revision(
                workspace_id, FirmwareId(firmware_id), RevisionId(revision_id)
            )


@contextmanager
def _refusals() -> Iterator[None]:
    """Turns a firmware refusal into the status the design's table gives it.

    One place rather than a handler full of `except` clauses, and no global handler: the
    mapping is part of this router's contract, not the application's, as projects' is.
    """
    try:
        yield
    except FirmwareError as error:
        raise HTTPException(_status_of(error), str(error)) from error


@contextmanager
def _firmware_refusals() -> Iterator[None]:
    """A refused write, answered with its code, field and item instead of a sentence (decision
    13), and a refused delete with the flashes in its way (15's decision 13).

    Nested inside `_refusals()` and never outside it, as projects' `_net_refusals()` is: a
    `FirmwareRefusalError` is a `FirmwareError` too, so its structured detail has to be built
    first, or the generic mapping would flatten it to a message and the editor would have no
    field to mark. A missing firmware, version, file, revision, unit or flash falls through to
    that mapping as a plain 404.
    """
    try:
        yield
    except FirmwareRefusalError as error:
        refusal = FirmwareRefusalResponse.from_error(error)
        raise HTTPException(_status_of(error), refusal.model_dump(mode="json")) from error


def _status_of(error: FirmwareError) -> int:
    for kind in type(error).__mro__:
        found = _STATUS_BY_ERROR.get(kind)
        if found is not None:
            return found
    return REFUSED


def _details(body: FirmwareRequest) -> FirmwareDetails:
    description = _given(body.description)
    return FirmwareDetails(
        name=FirmwareName(body.name),
        target=BoardTarget(body.target),
        framework=Framework(body.framework),
        description=None if description is None else Description(description),
    )


def _changelog(text: str | None) -> Changelog | None:
    given = _given(text)
    return None if given is None else Changelog(given)


def _new_file(body: SourceFileRequest) -> NewSourceFile:
    """The file as sent: the use case reads its path and text, so a refusal of the text names
    the file by its path (requirement 7.5)."""
    return NewSourceFile(path=body.path, text=body.content)


def _new_flash(body: FlashRequest) -> NewFlash:
    """The flash as sent, its time moved to UTC and blank notes read as none (1.9).

    In UTC because PostgreSQL answers a stored time in UTC: the time a flash was logged at with
    an offset, `-03:00`, would otherwise come back in the 201 one way and in every later read
    another. The instant is the same, so the five minutes ahead it is checked against aren't
    moved.
    """
    flashed_at = None if body.flashed_at is None else body.flashed_at.astimezone(UTC)
    notes = _given(body.notes)
    return NewFlash(
        version_id=VersionId(body.version_id),
        flashed_at=flashed_at,
        notes=None if notes is None else FlashNotes(notes),
    )


def _given(text: str | None) -> str | None:
    """Blank text is nothing given (design's HTTP section): a cleared description, changelog or
    flash's notes means none, never a refusal for being empty."""
    return text if text is not None and text.strip() else None
