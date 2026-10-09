"""The small immutable values files are made of, each validating itself in `__post_init__`.

Every value normalizes through `object.__setattr__`, exactly as the catalog's `values.py`
does (ADR 0004). Domain code is plain Python: nothing here imports a framework.

`files` declares its own `WorkspaceId` instead of importing identity's, as `catalog` does;
promote it to the shared kernel when a third module needs it.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import NewType, Self
from uuid import UUID

from wiredex.files.domain.errors import FilesError, UnsupportedFileTypeError

WorkspaceId = NewType("WorkspaceId", UUID)
AttachmentId = NewType("AttachmentId", UUID)

# 64 lower-case hex characters: the SHA-256 of the bytes, the name a file is stored under.
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class Sha256:
    """A file's content address: the lower-case hex SHA-256 of its bytes."""

    value: str

    def __post_init__(self) -> None:
        digest = self.value.strip().lower()
        if not _SHA256.match(digest):
            raise FilesError(f"{self.value!r} is not a SHA-256: 64 hex characters")
        object.__setattr__(self, "value", digest)

    def __str__(self) -> str:
        return self.value


# 25 MiB, the cap requirement 2.4 gives an upload. Binary MiB, so the CHECK on `size` and the
# reader that stops at the limit agree to the byte.
MAX_FILE_SIZE = 25 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class FileSize:
    """A stored file's size in bytes: at least one byte (empty is refused), at most the cap."""

    value: int

    def __post_init__(self) -> None:
        if not 1 <= self.value <= MAX_FILE_SIZE:
            raise FilesError(f"a file needs between 1 and {MAX_FILE_SIZE} bytes")

    def __int__(self) -> int:
        return self.value


class MediaType(StrEnum):
    """The only types an upload may be, decided from the bytes themselves, never the name.

    PDF, three raster image formats and ZIP, for a revision's Gerbers (08's decision 13): a
    browser would run the script inside an SVG or an HTML file served from Wiredex's own
    origin (requirement 2.3), so those are refused however they are named or whatever type
    the browser claims (requirement 2.1). A ZIP is never rendered, only ever downloaded.
    """

    PDF = "application/pdf"
    PNG = "image/png"
    JPEG = "image/jpeg"
    WEBP = "image/webp"
    ZIP = "application/zip"

    @classmethod
    def sniff(cls, head: bytes) -> MediaType:
        """The type of `head`, read from its leading bytes (requirement 2.2).

        `head` is the start of the file; only a few bytes are read, enough for each
        signature. Anything that isn't one of the five accepted types, empty bytes included,
        is an `UnsupportedFileTypeError` (requirement 2.3).
        """
        if head.startswith(b"%PDF-"):
            return cls.PDF
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return cls.PNG
        if head.startswith(b"\xff\xd8\xff"):
            return cls.JPEG
        # RIFF container, four bytes of length, then the "WEBP" form type at offset 8.
        if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
            return cls.WEBP
        # A ZIP's first local file header. An empty archive starts with the end-of-directory
        # record instead (`PK\x05\x06`), which holds no Gerbers, so it stays refused.
        if head.startswith(b"PK\x03\x04"):
            return cls.ZIP
        raise UnsupportedFileTypeError("only PDF, PNG, JPEG, WebP and ZIP files are accepted")

    @property
    def previewable(self) -> bool:
        """Whether a browser shows it in place: the PDF and the images; never a ZIP."""
        return self is not MediaType.ZIP


class AttachmentKind(StrEnum):
    """What an attachment is: a datasheet, an image, a pinout diagram, a schematic, a
    revision's Gerbers, a firmware version's build, or anything else."""

    DATASHEET = "datasheet"
    IMAGE = "image"
    PINOUT_DIAGRAM = "pinout_diagram"
    SCHEMATIC = "schematic"
    GERBERS = "gerbers"
    FIRMWARE_BUILD = "firmware_build"
    OTHER = "other"

    def fits(self, subject: SubjectKind) -> bool:
        """Whether this kind goes on that subject: a build on a firmware version, which takes
        nothing else, and every other kind anywhere else (20-firmware-builds, 1.8). The flash
        dialog reads a version's attachments as builds, so no other kind may sit there."""
        return (self is AttachmentKind.FIRMWARE_BUILD) == (subject is SubjectKind.FIRMWARE_VERSION)

    @classmethod
    def suggested_for(cls, media_type: str, subject: SubjectKind) -> AttachmentKind:
        """The kind the web pre-selects from the sniffed type and what the file goes on.

        A part's PDF is a datasheet, a revision's a schematic; a revision's ZIP is its Gerbers,
        a part's is other; an image is an image anywhere. A type the subject refuses (a
        project's PDF or ZIP) suggests other, since the upload won't go through anyway. Only a
        suggestion; the owner changes it before or after the upload (08's decision 13). All
        but a firmware version's, which holds builds and nothing else (`fits`).
        """
        if subject is SubjectKind.FIRMWARE_VERSION:
            return cls.FIRMWARE_BUILD
        if media_type.startswith("image/"):
            return cls.IMAGE
        by_subject: dict[tuple[SubjectKind, str], AttachmentKind] = {
            (SubjectKind.REVISION, MediaType.PDF): cls.SCHEMATIC,
            (SubjectKind.REVISION, MediaType.ZIP): cls.GERBERS,
            (SubjectKind.PART, MediaType.PDF): cls.DATASHEET,
        }
        return by_subject.get((subject, media_type), cls.OTHER)


MAX_TITLE_LENGTH = 120


@dataclass(frozen=True, slots=True)
class AttachmentTitle:
    """What the part page shows for an attachment: trimmed, whitespace collapsed, 1-120 chars."""

    value: str

    def __post_init__(self) -> None:
        title = " ".join(self.value.split())
        if not 1 <= len(title) <= MAX_TITLE_LENGTH:
            raise FilesError(f"a title needs between 1 and {MAX_TITLE_LENGTH} characters")
        object.__setattr__(self, "value", title)

    @classmethod
    def from_filename(cls, name: str) -> Self:
        """A title from the uploaded file's name: any path is stripped, then trimmed and capped.

        Both `/` and `\\` separate, because the browser may send either. Whitespace is
        collapsed before the cap, so a long name keeps 120 usable characters, not 120 that
        might be mostly spaces; a name with nothing usable left is refused, like any bad title.
        """
        base = re.split(r"[/\\]", name)[-1]
        collapsed = " ".join(base.split())
        return cls(collapsed[:MAX_TITLE_LENGTH])

    def __str__(self) -> str:
        return self.value


class SubjectKind(StrEnum):
    """What an attachment belongs to: a part, a project's photos, a revision's files, a
    released firmware version's builds."""

    PART = "part"
    PROJECT = "project"
    REVISION = "revision"
    FIRMWARE_VERSION = "firmware_version"

    @property
    def noun(self) -> str:
        """The subject as a sentence names it: *that firmware version doesn't exist*."""
        return self.value.replace("_", " ")

    @property
    def takes(self) -> str:
        """What to say to a type this subject refuses."""
        if self is SubjectKind.FIRMWARE_VERSION:
            return "a firmware version takes a build: a ZIP of its binaries"
        return "a project takes photos: PNG, JPEG or WebP"

    def accepts(self, media_type: MediaType) -> bool:
        """A project takes photos, so images only; a firmware version takes a build, a ZIP; a
        part and a revision take every type.

        A project's section is a gallery, which would hide a PDF (design decision 12). A
        build is the binaries zipped with their offsets (20-firmware-builds, decision 1).
        """
        if self is SubjectKind.PROJECT:
            return media_type.value.startswith("image/")
        if self is SubjectKind.FIRMWARE_VERSION:
            return media_type is MediaType.ZIP
        return True


@dataclass(frozen=True, slots=True)
class Subject:
    """What an attachment belongs to: a kind and the id of the thing, e.g. `part:<uuid>`."""

    kind: SubjectKind
    id: UUID

    @classmethod
    def parse(cls, text: str) -> Self:
        """Reads `part:<uuid>`, `project:<uuid>`, `revision:<uuid>` or
        `firmware_version:<uuid>`. A missing separator, an unknown kind or a bad UUID is
        refused."""
        kind, sep, raw_id = text.partition(":")
        if not sep:
            raise FilesError(f"{text!r} is not a subject like part:<uuid>")
        try:
            subject_kind = SubjectKind(kind)
        except ValueError as exc:
            raise FilesError(f"{kind!r} is not a subject kind") from exc
        try:
            return cls(subject_kind, UUID(raw_id))
        except ValueError as exc:
            raise FilesError(f"{raw_id!r} is not a UUID") from exc

    def __str__(self) -> str:
        return f"{self.kind.value}:{self.id}"
