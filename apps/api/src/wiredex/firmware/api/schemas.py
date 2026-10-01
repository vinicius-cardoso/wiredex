"""What firmware takes and gives over HTTP, in primitives only.

No domain object reaches a field: the `from_*` classmethods do the converting, as projects' do.
Requests carry text as typed; the router turns a blank description or changelog into none and
hands the rest to the domain's values, which normalize or refuse it (design's HTTP section).

Every schema is named apart from the other modules' (ADR 0010: the names are the generated
client's contract), so OpenAPI holds each once. A version is `FirmwareVersionResponse`, not the
design's `VersionResponse`, which `GET /api/version` already answers.
"""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field

from wiredex.firmware.application.ports import (
    FirmwareSummary,
    FirmwareView,
    RevisionFacts,
    VersionSummary,
    VersionView,
)
from wiredex.firmware.domain.errors import FirmwareRefusalError
from wiredex.firmware.domain.source import MAX_FILES, MAX_VERSION_BYTES, SourceFile
from wiredex.firmware.domain.values import Framework
from wiredex.firmware.domain.version import FirmwareVersion, VersionStatus

# The frameworks, the statuses, the refusal codes and their fields, spelled out for the wire so
# the generated client gets unions it can switch on: the web picks a word and a sentence per
# value, typed against these, so none ships untranslated (decision 13). Tests keep each in step
# with its enum.
type FrameworkName = Literal["arduino", "platformio", "esp_idf", "micropython", "other"]
type VersionStatusName = Literal["draft", "released"]
type FirmwareRefusalCodeName = Literal[
    "invalid_name",
    "name_taken",
    "invalid_target",
    "invalid_description",
    "invalid_version",
    "version_taken",
    "invalid_changelog",
    "version_released",
    "no_files",
    "no_changelog",
    "invalid_path",
    "path_taken",
    "not_text",
    "too_many_files",
    "version_too_large",
]
type FirmwareFieldName = Literal[
    "name", "target", "description", "version", "changelog", "path", "content", "files"
]


class FirmwareRequest(BaseModel):
    """A firmware's name, target, framework and description, replacing the stored ones whole
    (requirement 1.7)."""

    name: str
    target: str
    framework: FrameworkName
    description: str | None = None


class NewFirmwareRequest(FirmwareRequest):
    """A new firmware, with no versions; for a revision, it runs on it from the start (3.3)."""

    revision_id: UUID | None = None


class NewVersionRequest(BaseModel):
    """A new draft. No number takes the suggested one (5.4); no version to start from makes it
    empty, and one copies that version's files (5.5)."""

    version: str | None = None
    from_version_id: UUID | None = None


class VersionRequest(BaseModel):
    """A draft's number and changelog, replacing the stored ones whole (requirement 5.7)."""

    version: str
    changelog: str | None = None


class SourceFileRequest(BaseModel):
    """A file to add, or the whole of a file being edited: its path and its text (7.8)."""

    # No length bounds: the domain's values refuse a path or a text with their own codes, the
    # file named (7.2, 7.5) and the room left said (7.7). A bound would answer a generic 422
    # instead, and a 500 for half of a surrogate pair, whose input the answer can't encode. The
    # body is parsed whole either way.
    path: str
    content: str


class NewSourceFilesRequest(BaseModel):
    """One file or several, added all together or none (requirement 7.1, decision 10)."""

    files: list[SourceFileRequest] = Field(min_length=1, max_length=MAX_FILES)


class RunsOnResponse(BaseModel):
    """A revision a firmware runs on, named by its project, label and summary (3.5)."""

    revision_id: UUID
    project_id: UUID
    project_name: str
    label: str
    summary: str | None

    @classmethod
    def from_facts(cls, facts: RevisionFacts) -> Self:
        return cls(
            revision_id=facts.revision_id,
            project_id=facts.project_id,
            project_name=facts.project_name,
            label=facts.label,
            summary=facts.summary,
        )


class VersionTagResponse(BaseModel):
    """A version by its id and number, enough to name it and link to it."""

    id: UUID
    version: str

    @classmethod
    def from_version(cls, version: FirmwareVersion) -> Self:
        return cls(id=version.id, version=str(version.number))


class VersionSummaryResponse(BaseModel):
    """A version as its firmware's page lists it, with its file count and bytes (1.8)."""

    id: UUID
    version: str
    status: VersionStatusName
    based_on: UUID | None
    released_at: datetime | None
    created_at: datetime
    updated_at: datetime
    files: int
    size: int

    @classmethod
    def from_summary(cls, summary: VersionSummary) -> Self:
        version = summary.version
        return cls(
            id=version.id,
            version=str(version.number),
            status=_status_name(version.status),
            based_on=version.based_on,
            released_at=version.released_at,
            created_at=version.created_at,
            updated_at=version.updated_at,
            files=summary.files,
            size=summary.size,
        )


class FirmwareSummaryResponse(BaseModel):
    """A row of the firmware list, or of a revision's firmware (requirements 2.1, 3.4)."""

    id: UUID
    name: str
    target: str
    framework: FrameworkName
    latest_release: VersionTagResponse | None
    versions: int
    drafts: int
    updated_at: datetime

    @classmethod
    def from_summary(cls, summary: FirmwareSummary) -> Self:
        firmware = summary.firmware
        return cls(
            id=firmware.id,
            name=str(firmware.name),
            target=str(firmware.target),
            framework=_framework_name(firmware.framework),
            latest_release=_tag(summary.latest_release),
            versions=summary.versions,
            drafts=summary.drafts,
            updated_at=firmware.updated_at,
        )


class FirmwareResponse(BaseModel):
    """A firmware's page (requirement 1.8): its details, the revisions it runs on in link order,
    its versions highest first, its latest release and the number a new version would take,
    which the new version dialog prefills."""

    id: UUID
    name: str
    target: str
    framework: FrameworkName
    description: str | None
    created_at: datetime
    updated_at: datetime
    runs_on: list[RunsOnResponse]
    versions: list[VersionSummaryResponse]
    latest_release: VersionTagResponse | None
    suggested_version: str

    @classmethod
    def from_view(cls, view: FirmwareView) -> Self:
        firmware = view.firmware
        return cls(
            id=firmware.id,
            name=str(firmware.name),
            target=str(firmware.target),
            framework=_framework_name(firmware.framework),
            description=_text(firmware.description),
            created_at=firmware.created_at,
            updated_at=firmware.updated_at,
            runs_on=[RunsOnResponse.from_facts(facts) for facts in view.runs_on],
            versions=[VersionSummaryResponse.from_summary(summary) for summary in view.versions],
            latest_release=_tag(view.latest_release),
            suggested_version=str(view.suggested),
        )


class SourceFileResponse(BaseModel):
    """A file of a version: its path, its text as stored, its bytes of UTF-8 and its lines."""

    id: UUID
    path: str
    content: str
    size: int
    lines: int

    @classmethod
    def from_file(cls, file: SourceFile) -> Self:
        return cls(
            id=file.id,
            path=str(file.path),
            content=str(file.text),
            size=file.text.size,
            lines=file.text.lines,
        )


class FirmwareVersionResponse(BaseModel):
    """A version as it opens (requirement 5.8): its number, status, changelog, base, release
    date and whether it can be edited, which only a draft can; its files in requirement 7.10's
    order; and its total size beside the limits a write is checked against."""

    id: UUID
    firmware_id: UUID
    version: str
    status: VersionStatusName
    changelog: str | None
    based_on: VersionTagResponse | None
    released_at: datetime | None
    created_at: datetime
    updated_at: datetime
    editable: bool
    files: list[SourceFileResponse]
    size: int
    size_limit: int
    file_limit: int

    @classmethod
    def from_view(cls, view: VersionView) -> Self:
        version = view.version
        return cls(
            id=version.id,
            firmware_id=version.firmware_id,
            version=str(version.number),
            status=_status_name(version.status),
            changelog=_text(version.changelog),
            based_on=_tag(view.base),
            released_at=version.released_at,
            created_at=version.created_at,
            updated_at=version.updated_at,
            editable=version.status is VersionStatus.DRAFT,
            files=[SourceFileResponse.from_file(file) for file in view.files.items],
            size=view.files.size,
            size_limit=MAX_VERSION_BYTES,
            file_limit=MAX_FILES,
        )


class FirmwareRefusalResponse(BaseModel):
    """The `detail` of a refused firmware write (decision 13, the design's Error Handling).

    The sentence stays English; the code is what the web translates, and the field is where the
    editor shows it. `item` is the name, number or path as typed, or the path of a file whose
    text is refused.
    """

    message: str
    code: FirmwareRefusalCodeName
    field: FirmwareFieldName | None
    item: str | None

    @classmethod
    def from_error(cls, error: FirmwareRefusalError) -> Self:
        # An enum's value is the literal it holds, so a new code or field stops type-checking
        # here until the wire contract above lists it too.
        code: FirmwareRefusalCodeName = error.code.value
        field: FirmwareFieldName | None = None if error.field is None else error.field.value
        return cls(message=str(error), code=code, field=field, item=error.item)


def _framework_name(framework: Framework) -> FrameworkName:
    name: FrameworkName = framework.value
    return name


def _status_name(status: VersionStatus) -> VersionStatusName:
    name: VersionStatusName = status.value
    return name


def _tag(version: FirmwareVersion | None) -> VersionTagResponse | None:
    return None if version is None else VersionTagResponse.from_version(version)


def _text(value: object) -> str | None:
    return None if value is None else str(value)
