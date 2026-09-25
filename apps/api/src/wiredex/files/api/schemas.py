"""What the files module takes and gives over HTTP, in primitives only.

No domain object reaches a field: the `from_view` classmethod does the converting, as
catalog's `from_*` do. An upload is multipart, so it isn't a body model here — the router
reads its form fields directly; what this file describes is the one response every route
that returns an attachment shares.
"""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel

from wiredex.files.application.attachments import AttachmentView
from wiredex.files.domain.values import AttachmentKind, AttachmentTitle

# The kinds spelled out for the wire, so the generated client gets a union it can switch on.
# A test keeps this list in step with `AttachmentKind`, as catalog does for its own enums.
type AttachmentKindName = Literal["datasheet", "image", "pinout_diagram", "other"]
# The four media types an attachment's bytes may be, likewise as a closed set for the client.
type MediaTypeName = Literal["application/pdf", "image/png", "image/jpeg", "image/webp"]


class ChangeAttachmentRequest(BaseModel):
    """A rename, a re-kind, or both. What the body left out is left alone (requirement 4.1).

    The domain owns the rules: a title is trimmed and capped, a kind is one of the four, so
    the value objects validate here and a bad one is the router's 422. Both left out is a
    patch that carries nothing, which the use case treats as a no-op — nothing to commit.
    """

    title: str | None = None
    kind: AttachmentKindName | None = None

    def title_value(self) -> AttachmentTitle | None:
        return None if self.title is None else AttachmentTitle(self.title)

    def kind_value(self) -> AttachmentKind | None:
        return None if self.kind is None else AttachmentKind(self.kind)


class AttachmentResponse(BaseModel):
    """One attachment as a part page shows it, with the link its content is read from.

    `subject` travels as the `part:<uuid>` string it parses from, so the web sends it back
    unchanged when it lists or uploads. `size` is the file's byte count and `media_type` its
    sniffed type; `content_url` is the API path the bytes are streamed from (design §6).
    """

    id: UUID
    subject: str
    kind: AttachmentKindName
    title: str
    media_type: MediaTypeName
    size: int
    created_at: datetime
    content_url: str

    @classmethod
    def from_view(cls, view: AttachmentView, content_url: str) -> Self:
        attachment = view.attachment
        return cls(
            id=attachment.id,
            subject=str(attachment.subject),
            kind=_kind_name(attachment.kind),
            title=str(attachment.title),
            media_type=_media_type_name(view.file.media_type),
            size=int(view.file.size),
            created_at=attachment.created_at,
            content_url=content_url,
        )


def _kind_name(kind: object) -> AttachmentKindName:
    # An enum's value is the literal it holds, so a fifth kind stops type-checking here
    # until the wire contract above lists it too, as catalog's `_kind_name` does.
    name: AttachmentKindName = kind.value  # type: ignore[attr-defined]
    return name


def _media_type_name(media_type: object) -> MediaTypeName:
    name: MediaTypeName = media_type.value  # type: ignore[attr-defined]
    return name
