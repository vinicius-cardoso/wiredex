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

from pydantic import AwareDatetime, BaseModel, Field

from wiredex.firmware.application.ports import (
    BoardView,
    FirmwareSummary,
    FirmwareView,
    FlashView,
    RevisionFacts,
    UnitFirmwareView,
    VersionSummary,
    VersionView,
)
from wiredex.firmware.domain.errors import (
    FirmwareFlashedError,
    FirmwareRefusalError,
    VersionFlashedError,
)
from wiredex.firmware.domain.flash import BlockingFlash, UnitFacts
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
    "not_released",
    "unit_retired",
    "flashed_in_future",
    "invalid_notes",
    "version_flashed",
    "firmware_flashed",
]
type FirmwareFieldName = Literal[
    "name",
    "target",
    "description",
    "version",
    "changelog",
    "path",
    "content",
    "files",
    "unit",
    "flashed_at",
    "notes",
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


class FlashRequest(BaseModel):
    """A flash logged on the unit it is sent under (15-flash-log requirement 1): the released
    version flashed, when, and notes. No time is now (1.2). A time must carry its offset: one
    without would mean the browser's clock to the owner and the server's to the API."""

    version_id: UUID
    flashed_at: AwareDatetime | None = None
    # No length bound, as `SourceFileRequest` has none: `FlashNotes` refuses long notes with
    # its own code, and a bound would answer a 500 for half of a surrogate pair.
    notes: str | None = None


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


class UnitTagResponse(BaseModel):
    """A unit by its id and short code, enough to name it and link to it (15-flash-log)."""

    id: UUID
    code: str

    @classmethod
    def from_facts(cls, unit: UnitFacts) -> Self:
        return cls(id=unit.unit_id, code=str(unit.code))


class FlashResponse(BaseModel):
    """One entry of a unit's flash log (15-flash-log requirement 2.1): the unit by the code it
    recorded, which outlives the unit (1.8); the firmware and version flashed; the revision it
    recorded while the workspace still holds it (1.7); when it was flashed, in UTC, and its
    notes; and when it was logged, which orders two flashes with one time."""

    id: UUID
    unit: UnitTagResponse
    firmware_id: UUID
    firmware_name: str
    version: VersionTagResponse
    revision: RunsOnResponse | None
    flashed_at: datetime
    notes: str | None
    created_at: datetime

    @classmethod
    def from_view(cls, view: FlashView) -> Self:
        entry = view.entry
        flash = entry.flash
        return cls(
            id=flash.id,
            unit=UnitTagResponse(id=flash.unit_id, code=str(flash.unit_code)),
            firmware_id=entry.firmware_id,
            firmware_name=str(entry.firmware_name),
            version=VersionTagResponse(id=flash.version_id, version=str(entry.number)),
            revision=None if view.revision is None else RunsOnResponse.from_facts(view.revision),
            flashed_at=flash.flashed_at,
            notes=_text(flash.notes),
            created_at=flash.created_at,
        )


class UnitFirmwareResponse(BaseModel):
    """What a board runs (15-flash-log requirement 2): the unit and whether it is retired, its
    current flash, the newer release of that flash's firmware, and its log newest first."""

    unit: UnitTagResponse
    retired: bool
    current: FlashResponse | None
    newer_release: VersionTagResponse | None
    flashes: list[FlashResponse]

    @classmethod
    def from_view(cls, view: UnitFirmwareView) -> Self:
        current = view.current
        return cls(
            unit=UnitTagResponse.from_facts(view.unit),
            retired=view.unit.retired,
            current=None if current is None else FlashResponse.from_view(current),
            newer_release=_tag(view.newer_release),
            flashes=[FlashResponse.from_view(flash) for flash in view.flashes],
        )


class BoardResponse(BaseModel):
    """A board a firmware runs on (15-flash-log requirement 4.1): the unit, the revision holding
    it now, its current flash, and the firmware's newer release when there is one."""

    unit: UnitTagResponse
    revision: RunsOnResponse | None
    flash: FlashResponse
    newer_release: VersionTagResponse | None

    @classmethod
    def from_view(cls, view: BoardView) -> Self:
        return cls(
            unit=UnitTagResponse.from_facts(view.unit),
            revision=None if view.revision is None else RunsOnResponse.from_facts(view.revision),
            flash=FlashResponse.from_view(view.current),
            newer_release=_tag(view.newer_release),
        )


class BlockingFlashResponse(BaseModel):
    """A flash that keeps a version or a firmware from being deleted (15-flash-log decision 6):
    the web links its unit only while inventory holds it, and offers to remove it either way, a
    deleted unit's entries included."""

    id: UUID
    unit: UnitTagResponse
    unit_present: bool
    version: VersionTagResponse
    flashed_at: datetime

    @classmethod
    def from_blocking(cls, blocking: BlockingFlash) -> Self:
        flash = blocking.flash
        return cls(
            id=flash.id,
            unit=UnitTagResponse(id=flash.unit_id, code=str(flash.unit_code)),
            unit_present=blocking.unit_present,
            version=VersionTagResponse(id=flash.version_id, version=str(blocking.number)),
            flashed_at=flash.flashed_at,
        )


class FirmwareRefusalResponse(BaseModel):
    """The `detail` of a refused firmware write (decision 13, the design's Error Handling).

    The sentence stays English; the code is what the web translates, and the field is where the
    editor shows it. `item` is the name, number or path as typed, or the path of a file whose
    text is refused. `flashes` are the entries a refused delete names, so the page can list them
    and remove each (15-flash-log decision 13); every other refusal answers none.
    """

    message: str
    code: FirmwareRefusalCodeName
    field: FirmwareFieldName | None
    item: str | None
    flashes: list[BlockingFlashResponse]

    @classmethod
    def from_error(cls, error: FirmwareRefusalError) -> Self:
        # An enum's value is the literal it holds, so a new code or field stops type-checking
        # here until the wire contract above lists it too.
        code: FirmwareRefusalCodeName = error.code.value
        field: FirmwareFieldName | None = None if error.field is None else error.field.value
        blocking = (
            error.flashes if isinstance(error, VersionFlashedError | FirmwareFlashedError) else ()
        )
        return cls(
            message=str(error),
            code=code,
            field=field,
            item=error.item,
            flashes=[BlockingFlashResponse.from_blocking(one) for one in blocking],
        )


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
