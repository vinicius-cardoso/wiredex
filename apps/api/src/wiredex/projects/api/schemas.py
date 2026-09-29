"""What projects takes and gives over HTTP, in primitives only.

No domain object reaches a field: the `from_*` classmethods do the converting, as catalog's
and inventory's do. Requests carry text as typed; the router turns a blank description,
summary or notes into none and hands the rest to the domain's values, which normalize or
refuse it (design's HTTP API).
"""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field

from wiredex.projects.application.ports import BomView, ProjectSummary, ProjectView, TagCount
from wiredex.projects.domain.bom import BomLine
from wiredex.projects.domain.errors import BomField, ContentError, DesignatorTakenError
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.shortage import (
    PartFacts,
    PartShortage,
    ShortageReport,
    ShortageSummary,
    StockStatus,
)
from wiredex.projects.domain.values import MAX_TAGS, RevisionStatus

# ADR 0003's four states spelled out for the wire, so the generated client gets a union it
# can switch on. A test keeps this in step with the `RevisionStatus` enum.
type RevisionStatusName = Literal["draft", "reserved", "built", "dismantled"]
# The report's statuses, a line's fields and the refusal codes, spelled out for the same
# reason: the web picks a colour and a sentence per value, typed against these unions, so a
# value can't ship without one. Tests keep each in step with its enum.
type StockStatusName = Literal["covered", "short", "not_stocked", "unknown_part"]
type BomFieldName = Literal["part", "designators", "quantity", "notes"]
type BomRefusalCodeName = Literal[
    "invalid_designator",
    "invalid_range",
    "repeated_designator",
    "too_many_designators",
    "designator_taken",
    "quantity_mismatch",
    "invalid_quantity",
    "invalid_notes",
    "unknown_part",
    "too_many_lines",
    "revision_locked",
]

# The transport bound on a line's typed text (design's Limits): far past what the domain
# takes, so the domain's own refusal names the problem, while a body of megabytes never
# reaches it.
MAX_TYPED_LENGTH = 4_000


class CreateProjectRequest(BaseModel):
    """A new project. Its revision A comes with it (design decision 2)."""

    name: str
    description: str | None = None
    # Capped as given, before normalizing: more than twenty texts is a mistake, not a request
    # (design's error table).
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)


class UpdateProjectRequest(BaseModel):
    """A project's name, description and tags, replacing the stored ones whole (1.5)."""

    name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)


class NewRevisionRequest(BaseModel):
    """A revision to add or fork. No label takes the suggested one (decision 4)."""

    label: str | None = None
    summary: str | None = None
    notes: str | None = None


class UpdateRevisionRequest(BaseModel):
    """A revision's label, summary and notes, replacing the stored ones whole (4.8)."""

    label: str
    summary: str | None = None
    notes: str | None = None


class RevisionResponse(BaseModel):
    """A revision on the wire: `A - breadboard` is the label `A` and the summary."""

    id: UUID
    project_id: UUID
    label: str
    summary: str | None
    notes: str | None
    status: RevisionStatusName
    forked_from: UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_revision(cls, revision: Revision) -> Self:
        return cls(
            id=revision.id,
            project_id=revision.project_id,
            label=str(revision.label),
            summary=_text(revision.summary),
            notes=_text(revision.notes),
            status=_status_name(revision.status),
            forked_from=revision.forked_from,
            created_at=revision.created_at,
            updated_at=revision.updated_at,
        )


class RevisionSummaryResponse(BaseModel):
    """The latest revision as a list row shows it: `B - perfboard`, with its status."""

    id: UUID
    label: str
    summary: str | None
    status: RevisionStatusName

    @classmethod
    def from_revision(cls, revision: Revision) -> Self:
        return cls(
            id=revision.id,
            label=str(revision.label),
            summary=_text(revision.summary),
            status=_status_name(revision.status),
        )


class ProjectResponse(BaseModel):
    """A project page (requirement 1.6): its revisions oldest first, the one it opens on, and
    the label a new revision would take, which the fork dialog prefills. `next_label` is null
    only when no label can be suggested within 16 characters."""

    id: UUID
    name: str
    description: str | None
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    revisions: list[RevisionResponse]
    latest_revision_id: UUID
    next_label: str | None

    @classmethod
    def from_view(cls, view: ProjectView, latest: Revision) -> Self:
        """`latest` is passed in rather than read here, because the view types it as
        optional and the router decides what a project with no revision means."""
        project = view.project
        suggested = view.revisions.suggested_label()
        return cls(
            id=project.id,
            name=str(project.name),
            description=_text(project.description),
            tags=_tags(project),
            created_at=project.created_at,
            updated_at=project.updated_at,
            revisions=[RevisionResponse.from_revision(r) for r in view.revisions.items],
            latest_revision_id=latest.id,
            next_label=None if suggested is None else str(suggested),
        )


class ProjectSummaryResponse(BaseModel):
    """A row of the project list (requirement 3.1)."""

    id: UUID
    name: str
    tags: list[str]
    revision_count: int
    latest_revision: RevisionSummaryResponse
    last_activity: datetime

    @classmethod
    def from_summary(cls, summary: ProjectSummary) -> Self:
        return cls(
            id=summary.project.id,
            name=str(summary.project.name),
            tags=_tags(summary.project),
            revision_count=summary.revision_count,
            latest_revision=RevisionSummaryResponse.from_revision(summary.latest),
            last_activity=summary.last_activity,
        )


class ProjectTagResponse(BaseModel):
    """A tag of the workspace and how many projects carry it (requirement 2.6)."""

    tag: str
    projects: int

    @classmethod
    def from_count(cls, count: TagCount) -> Self:
        return cls(tag=str(count.tag), projects=count.projects)


class BomLineRequest(BaseModel):
    """A line to add, or the whole of a line being edited (requirement 4.9).

    The designators are a list as typed, `r1-4, R7`; blank text is none. The quantity may be
    left out when there are designators, since their count is the quantity (decision 7).
    """

    part_id: UUID
    designators: str = Field(default="", max_length=MAX_TYPED_LENGTH)
    quantity: int | None = None
    notes: str | None = Field(default=None, max_length=MAX_TYPED_LENGTH)


class BomLineResponse(BaseModel):
    """A line, its designators both as a list and as canonical text (requirement 4.11)."""

    id: UUID
    revision_id: UUID
    part_id: UUID
    designators: list[str]
    designator_text: str
    quantity: int
    notes: str | None
    created_at: datetime

    @classmethod
    def from_line(cls, line: BomLine) -> Self:
        content = line.content
        return cls(
            id=line.id,
            revision_id=line.revision_id,
            part_id=content.part_id,
            designators=[str(designator) for designator in content.designators],
            designator_text=content.designators.text(),
            quantity=content.quantity.value,
            notes=_text(content.notes),
            created_at=line.created_at,
        )


class BomPartFactsResponse(BaseModel):
    """What the catalog says about a part on the BOM, as it stands at this read (8.3)."""

    name: str
    manufacturer: str | None
    mpn: str | None
    package: str | None
    tracked_individually: bool
    not_stocked: bool

    @classmethod
    def from_facts(cls, facts: PartFacts) -> Self:
        return cls(
            name=facts.name,
            manufacturer=facts.manufacturer,
            mpn=facts.mpn,
            package=facts.package,
            tracked_individually=facts.tracked_individually,
            not_stocked=facts.not_stocked,
        )


class BomPartResponse(BaseModel):
    """One part of the report (requirement 6.1). An unknown part has no facts; it and a
    consumable have no available stock and are never short (6.4, 6.5)."""

    part_id: UUID
    lines: int
    need: int
    available: int | None
    short: int
    status: StockStatusName
    part: BomPartFactsResponse | None

    @classmethod
    def from_shortage(cls, shortage: PartShortage) -> Self:
        return cls(
            part_id=shortage.part_id,
            lines=shortage.need.lines,
            need=shortage.need.quantity,
            available=shortage.available,
            short=shortage.short,
            status=_stock_status_name(shortage.status),
            part=None if shortage.part is None else BomPartFactsResponse.from_facts(shortage.part),
        )


class ShortageSummaryResponse(BaseModel):
    """The report's counts, and whether the BOM is complete (requirement 6.6)."""

    lines: int
    parts: int
    short_parts: int
    short_pieces: int
    not_stocked_parts: int
    unknown_parts: int
    complete: bool

    @classmethod
    def from_summary(cls, summary: ShortageSummary) -> Self:
        return cls(
            lines=summary.lines,
            parts=summary.parts,
            short_parts=summary.short_parts,
            short_pieces=summary.short_pieces,
            not_stocked_parts=summary.not_stocked_parts,
            unknown_parts=summary.unknown_parts,
            complete=summary.complete,
        )


class ShortageReportResponse(BaseModel):
    """The summary, and each part in the order it first appears on the BOM."""

    summary: ShortageSummaryResponse
    parts: list[BomPartResponse]

    @classmethod
    def from_report(cls, report: ShortageReport) -> Self:
        return cls(
            summary=ShortageSummaryResponse.from_summary(report.summary),
            parts=[BomPartResponse.from_shortage(part) for part in report.parts],
        )


class BomResponse(BaseModel):
    """A revision's BOM: its lines oldest first, its report, and whether it can change,
    which only a draft's can (requirement 5.2)."""

    revision_id: UUID
    status: RevisionStatusName
    editable: bool
    lines: list[BomLineResponse]
    report: ShortageReportResponse

    @classmethod
    def from_view(cls, view: BomView) -> Self:
        return cls(
            revision_id=view.revision.id,
            status=_status_name(view.revision.status),
            editable=view.editable,
            lines=[BomLineResponse.from_line(line) for line in view.bom.lines],
            report=ShortageReportResponse.from_report(view.report),
        )


class BomRefusalResponse(BaseModel):
    """The `detail` of a refused line write (design's Error Handling).

    The sentence stays English; the code is what the web translates, and the field is where
    the editor shows it. `item` names the designator or the typed item refused; a designator
    another line holds also names that line, by id and canonical text.
    """

    message: str
    code: BomRefusalCodeName
    field: BomFieldName | None
    item: str | None
    line_id: UUID | None
    line: str | None

    @classmethod
    def from_error(cls, error: ContentError) -> Self:
        taken = error if isinstance(error, DesignatorTakenError) else None
        code: BomRefusalCodeName = error.code.value
        return cls(
            message=str(error),
            code=code,
            field=_bom_field_name(error.field),
            item=error.item,
            line_id=None if taken is None else taken.line_id,
            line=None if taken is None else taken.line,
        )


def _stock_status_name(status: StockStatus) -> StockStatusName:
    name: StockStatusName = status.value
    return name


def _bom_field_name(field: BomField | None) -> BomFieldName | None:
    if field is None:
        return None
    name: BomFieldName = field.value
    return name


def _status_name(status: RevisionStatus) -> RevisionStatusName:
    # An enum's value is the literal it holds, so a fifth state stops type-checking here
    # until the wire contract above lists it too.
    name: RevisionStatusName = status.value
    return name


def _tags(project: Project) -> list[str]:
    return list(project.tags.texts())


def _text(value: object) -> str | None:
    return None if value is None else str(value)
