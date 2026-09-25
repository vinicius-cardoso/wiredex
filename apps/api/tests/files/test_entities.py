from datetime import UTC, datetime
from uuid import UUID, uuid4

from wiredex.files.domain.entities import Attachment, StoredFile
from wiredex.files.domain.values import (
    AttachmentId,
    AttachmentKind,
    AttachmentTitle,
    FileSize,
    MediaType,
    Sha256,
    Subject,
    SubjectKind,
    WorkspaceId,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
DIGEST = "a" * 64


def a_stored_file(workspace_id: WorkspaceId, sha256: str = DIGEST) -> StoredFile:
    return StoredFile(
        workspace_id=workspace_id,
        sha256=Sha256(sha256),
        media_type=MediaType.PDF,
        size=FileSize(1024),
        created_at=NOW,
    )


def an_attachment(
    kind: AttachmentKind = AttachmentKind.DATASHEET,
    title: str = "BME280 datasheet",
) -> Attachment:
    return Attachment(
        id=AttachmentId(uuid4()),
        workspace_id=WorkspaceId(uuid4()),
        subject=Subject(SubjectKind.PART, uuid4()),
        sha256=Sha256(DIGEST),
        kind=kind,
        title=AttachmentTitle(title),
        created_at=NOW,
    )


# --- StoredFile.object_key ----------------------------------------------------


def test_an_object_key_sits_under_the_workspace_prefix() -> None:
    workspace_id = WorkspaceId(UUID("11111111-1111-1111-1111-111111111111"))
    stored = a_stored_file(workspace_id)
    assert stored.object_key == f"workspaces/{workspace_id}/sha256/{DIGEST}"


def test_object_keys_of_two_workspaces_never_collide() -> None:
    a = a_stored_file(WorkspaceId(uuid4()))
    b = a_stored_file(WorkspaceId(uuid4()))
    # Same bytes, same digest, but different prefixes: two workspaces never share an object.
    assert a.sha256 == b.sha256
    assert a.object_key != b.object_key
    assert a.object_key.startswith(f"workspaces/{a.workspace_id}/")
    assert b.object_key.startswith(f"workspaces/{b.workspace_id}/")


# --- Attachment.rename --------------------------------------------------------


def test_renaming_to_a_new_title_changes_it() -> None:
    attachment = an_attachment(title="old title")
    changed = attachment.rename(AttachmentTitle("new title"))
    assert changed is True
    assert str(attachment.title) == "new title"


def test_renaming_to_the_same_title_is_a_no_op() -> None:
    attachment = an_attachment(title="BME280 datasheet")
    changed = attachment.rename(AttachmentTitle("BME280 datasheet"))
    assert changed is False
    assert str(attachment.title) == "BME280 datasheet"


# --- Attachment.rekind --------------------------------------------------------


def test_rekinding_to_a_new_kind_changes_it() -> None:
    attachment = an_attachment(kind=AttachmentKind.OTHER)
    changed = attachment.rekind(AttachmentKind.DATASHEET)
    assert changed is True
    assert attachment.kind is AttachmentKind.DATASHEET


def test_rekinding_to_the_same_kind_is_a_no_op() -> None:
    attachment = an_attachment(kind=AttachmentKind.DATASHEET)
    changed = attachment.rekind(AttachmentKind.DATASHEET)
    assert changed is False
    assert attachment.kind is AttachmentKind.DATASHEET
