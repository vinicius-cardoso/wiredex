"""A part's attachments over HTTP: list, upload, open, rename or re-kind, and remove.

A factory, as the other routers are: the use cases and the workspace dependency come in as
arguments, so the composition root decides what runs. `files` never imports identity —
`bootstrap/app.py` builds `current_workspace` from the session use cases and hands it over
(design §3), which is also where ADR 0008's session and CSRF checks come from, so a write
here is refused without them exactly as a catalog write is.

Two things this router owns beyond the usual request-to-use-case wiring. The upload is
bounded here, at the edge: it reads at most 25 MiB + 1 byte and refuses one byte over with
413, so an oversized file is turned away without being read whole into memory (requirement
2.4). And a file-store failure — the network, the credentials, the bucket — is not a files
rule being broken but the store being unreachable, so it answers 503 and is logged with its
cause and never with an object key (design, Error Handling).
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from wiredex.files.api.schemas import AttachmentResponse, ChangeAttachmentRequest
from wiredex.files.application.attachments import (
    Attach,
    ChangeAttachment,
    ClearWorkspace,
    Detach,
    ListAttachments,
    OpenAttachment,
    OpenedAttachment,
    PruneOrphans,
    Upload,
)
from wiredex.files.domain.errors import (
    AlreadyAttachedError,
    AttachmentNotFoundError,
    FilesError,
    FileTooLargeError,
    QuotaExceededError,
    SubjectNotFoundError,
    UnsupportedFileTypeError,
)
from wiredex.files.domain.values import (
    MAX_FILE_SIZE,
    AttachmentId,
    AttachmentKind,
    Subject,
    WorkspaceId,
)

logger = logging.getLogger(__name__)

# One more than the cap, so reading exactly this many bytes proves the upload is over: the
# 25-MiB-th byte is allowed, the next is not (requirement 2.4).
_READ_LIMIT = MAX_FILE_SIZE + 1
# The bytes are streamed to the reader in these chunks, matching the store's own read size.
_CHUNK_SIZE = 256 * 1024


@dataclass(frozen=True, slots=True)
class FilesUseCases:
    """What `create_router` takes, and what `bootstrap/files.py` builds for the app.

    A frozen dataclass like catalog's `CatalogUseCases`. `clear_workspace` and `prune_orphans`
    aren't reached over HTTP — they belong to the CLI (task 10) — but the one bundle wires
    both callers, so they travel with the rest.
    """

    attach: Attach
    list_attachments: ListAttachments
    open_attachment: OpenAttachment
    change_attachment: ChangeAttachment
    detach: Detach
    clear_workspace: ClearWorkspace
    prune_orphans: PruneOrphans


type CurrentWorkspaceDependency = Callable[[Request], Awaitable[WorkspaceId]]

# The design's error table, leaf by leaf. Anything else a files rule refuses — an empty
# file, a bad title, a malformed subject — is the request's content being unprocessable, so
# 422, as catalog's router falls through to.
_STATUS_BY_ERROR: Mapping[type[FilesError], int] = {
    SubjectNotFoundError: status.HTTP_404_NOT_FOUND,
    AttachmentNotFoundError: status.HTTP_404_NOT_FOUND,
    AlreadyAttachedError: status.HTTP_409_CONFLICT,
    FileTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
    QuotaExceededError: status.HTTP_413_CONTENT_TOO_LARGE,
    UnsupportedFileTypeError: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
}
REFUSED = status.HTTP_422_UNPROCESSABLE_CONTENT
STORE_UNREACHABLE = status.HTTP_503_SERVICE_UNAVAILABLE


def create_router(
    use_cases: FilesUseCases, current_workspace: CurrentWorkspaceDependency
) -> APIRouter:
    router = APIRouter(prefix="/files", tags=["files"])

    @router.get("/attachments")
    async def list_attachments(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        subject: str,
    ) -> list[AttachmentResponse]:
        """A part's attachments, newest first (requirement 1.6)."""
        with _refusals():
            views = await use_cases.list_attachments(workspace_id, _subject(subject))
        return [_response(view.attachment.id, view) for view in views]

    @router.post("/attachments", status_code=status.HTTP_201_CREATED)
    async def upload_attachment(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        subject: Annotated[str, Form()],
        kind: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
        title: Annotated[str | None, Form()] = None,
    ) -> AttachmentResponse:
        """Store an upload's bytes and attach them to a part (requirements 1.1, 1.3-1.5)."""
        data = await _read_bounded(file)
        with _refusals():
            upload = Upload(data, file.filename or "", _kind(kind), title)
            with _store_failures():
                view = await use_cases.attach(workspace_id, _subject(subject), upload)
        return _response(view.attachment.id, view)

    @router.get("/attachments/{attachment_id}/content")
    async def read_content(
        attachment_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        download: Annotated[int, Query()] = 0,
    ) -> StreamingResponse:
        """The bytes, streamed with their type and title; `?download=1` sends a download (3)."""
        with _refusals():
            opened = await use_cases.open_attachment(workspace_id, AttachmentId(attachment_id))
        return _content_response(opened, download=bool(download))

    @router.patch("/attachments/{attachment_id}")
    async def change_attachment(
        attachment_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        body: ChangeAttachmentRequest,
    ) -> AttachmentResponse:
        """Rename or re-kind an attachment (requirement 4.1). A no-op edit writes nothing."""
        with _refusals():
            attachment = await use_cases.change_attachment(
                workspace_id,
                AttachmentId(attachment_id),
                body.title_value(),
                body.kind_value(),
            )
            opened = await use_cases.open_attachment(workspace_id, attachment.id)
        return _response(attachment.id, opened)

    @router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def remove_attachment(
        attachment_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """Remove the attachment; its file goes when nothing else uses it (requirement 4.2)."""
        with _refusals(), _store_failures():
            await use_cases.detach(workspace_id, AttachmentId(attachment_id))

    return router


async def _read_bounded(file: UploadFile) -> bytes:
    """Read the upload, capped at 25 MiB + 1 byte, and refuse one byte over (requirement 2.4).

    Reading the cap plus one is what proves the file is over without reading the rest of it:
    a file exactly at the limit yields 25 MiB, one larger yields 25 MiB + 1 and is refused
    413 here, before the bytes are hashed or the store is touched.
    """
    data = await file.read(_READ_LIMIT)
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, "that file is larger than the 25 MB limit"
        )
    return data


def _content_response(opened: OpenedAttachment, *, download: bool) -> StreamingResponse:
    """The attachment's bytes, streamed, with the headers requirement 3 asks for.

    Inline by default so the browser shows a PDF or image in place, `attachment` with
    `?download=1` so it saves instead; either way the file name is the attachment's title,
    sent as an RFC 5987 `filename*` so a non-ASCII title survives. The bytes never change, so
    they are cached privately and forever, and `nosniff` keeps the browser from second-guessing
    the type we sniffed.
    """
    disposition = "attachment" if download else "inline"
    filename = quote(str(opened.attachment.title))
    headers = {
        "Content-Length": str(int(opened.file.size)),
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{filename}",
        "ETag": f'"{opened.file.sha256}"',
        "Cache-Control": "private, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(
        _streamed(opened.stream),
        media_type=str(opened.file.media_type),
        headers=headers,
    )


async def _streamed(stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Forward the store's chunks, turning a store failure mid-stream into a 503.

    The rows were already read when the response began, so a failure here is the store
    itself: it is logged with its cause and never with a key, and re-raised as the same 503
    the upload path gives.
    """
    try:
        async for chunk in stream:
            yield chunk
    except FilesError:
        raise
    except Exception as error:  # any store error is the store being unreachable.
        logger.warning("file store unreachable while streaming", exc_info=error)
        raise HTTPException(STORE_UNREACHABLE, _STORE_MESSAGE) from error


_STORE_MESSAGE = "the file store can't be reached right now"


@contextmanager
def _refusals() -> Iterator[None]:
    """Turn a files refusal into the status the design's table gives it.

    One place rather than a handler per route, and no global handler: the mapping is part of
    this router's contract, as catalog keeps its own.
    """
    try:
        yield
    except FilesError as error:
        raise HTTPException(_status_of(error), str(error)) from error


@contextmanager
def _store_failures() -> Iterator[None]:
    """Turn a file-store failure into a 503, logged with its cause and never with a key.

    Nested inside `_refusals()` on the write paths: a `FilesError` is a rule being broken and
    already has its status, so it falls through to the mapping; anything else raised while the
    store is being written is the store being unreachable (design, Error Handling).
    """
    try:
        yield
    except FilesError:
        raise
    except HTTPException:
        raise
    except Exception as error:  # any store error is the store being unreachable.
        logger.warning("file store unreachable", exc_info=error)
        raise HTTPException(STORE_UNREACHABLE, _STORE_MESSAGE) from error


def _status_of(error: FilesError) -> int:
    for kind in type(error).__mro__:
        found = _STATUS_BY_ERROR.get(kind)
        if found is not None:
            return found
    return REFUSED


def _response(attachment_id: AttachmentId, view: object) -> AttachmentResponse:
    """An attachment as the wire shows it, its content link built from its id.

    `view` is an `AttachmentView` or an `OpenedAttachment` — both carry the attachment and its
    file, which is all the response needs — so the one builder serves the list, the upload and
    the change routes.
    """
    return AttachmentResponse.from_view(view, _content_url(attachment_id))  # type: ignore[arg-type]


def _content_url(attachment_id: AttachmentId) -> str:
    """The API path an attachment's bytes are read from (design §6)."""
    return f"/api/files/attachments/{attachment_id}/content"


def _subject(text: str) -> Subject:
    return Subject.parse(text)


def _kind(value: str) -> AttachmentKind:
    try:
        return AttachmentKind(value)
    except ValueError as error:
        raise FilesError(f"{value!r} is not a kind") from error
