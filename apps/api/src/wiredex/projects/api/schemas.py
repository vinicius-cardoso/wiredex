"""What projects takes and gives over HTTP, in primitives only.

No domain object reaches a field: the `from_*` classmethods do the converting, as catalog's
and inventory's do. Requests carry text as typed; the router turns a blank description,
summary or notes into none and hands the rest to the domain's values, which normalize or
refuse it (design's HTTP API).
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self, cast
from uuid import UUID

from pydantic import BaseModel, Field

from wiredex.projects.application.ports import (
    BomView,
    HeldPart,
    Lifecycle,
    NetlistView,
    PartHoldingView,
    ProjectSummary,
    ProjectView,
    RevisionRef,
    TagCount,
)
from wiredex.projects.domain.bom import BomLine
from wiredex.projects.domain.errors import (
    AmbiguousPinError,
    BomField,
    ContentError,
    DesignatorTakenError,
    NetError,
    NetNameTakenError,
    RevisionContentLockedError,
)
from wiredex.projects.domain.lifecycle import (
    LifecycleRefusal,
    ShortError,
    Transition,
    TransitionNotAllowedError,
)
from wiredex.projects.domain.netlist import Net, Resolution
from wiredex.projects.domain.pins import PinFacts, PinType
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.shortage import (
    PartFacts,
    PartShortage,
    ShortageReport,
    ShortageSummary,
    StockStatus,
)
from wiredex.projects.domain.values import MAX_TAGS, PartId, RevisionStatus

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
# The four transitions and the ten refusal codes, spelled out for the wire like the statuses
# above: the web picks a sentence per code, typed against these unions, so a refusal can't
# ship untranslated (decision 14, requirement 13.13). Tests keep each in step with its enum.
type TransitionName = Literal["reserve", "cancel", "build", "dismantle"]
type RefusalCode = Literal[
    "transition_not_allowed",
    "empty_bom",
    "short",
    "unknown_unit",
    "repeated_unit",
    "unit_not_needed",
    "too_many_units",
    "unit_not_in_stock",
    "unknown_location",
    "stock_changed",
]

# A reserve names at most 100 units (decision 13); a 101st gets FastAPI's own 422.
MAX_NAMED_UNITS = 100

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


class ReserveRequest(BaseModel):
    """The units the owner names for a reserve, at most 100; empty means the automatic
    choice (decision 13). A repeated unit isn't a schema error: the use case refuses it as
    `repeated_unit`, naming it."""

    units: list[UUID] = Field(default_factory=list, max_length=MAX_NAMED_UNITS)


class DismantleRequest(BaseModel):
    """The location everything the build used returns to (requirement 6.1)."""

    location_id: UUID


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


# --- The build lifecycle over HTTP (decision 13) -------------------------------------------


class HeldLocationResponse(BaseModel):
    """One location a revision reserves a part in, and how many there (requirement 10.1)."""

    location_id: UUID
    location_code: str
    quantity: int


class HeldUnitResponse(BaseModel):
    """One unit a revision holds; `location_code` is null while it is built into the revision,
    sitting on a board rather than in a drawer (requirement 3.10)."""

    unit_id: UUID
    code: str
    location_code: str | None


class HeldPartResponse(BaseModel):
    """One part a reserved or built revision holds: its facts (null for an unknown part), what
    it reserves per location, what its build consumed, and its units (requirement 10.1)."""

    part_id: UUID
    part: BomPartFactsResponse | None
    reserved: list[HeldLocationResponse]
    consumed: int
    units: list[HeldUnitResponse]

    @classmethod
    def from_held(cls, held: HeldPart) -> Self:
        return cls(
            part_id=held.part_id,
            part=None if held.facts is None else BomPartFactsResponse.from_facts(held.facts),
            reserved=[
                HeldLocationResponse(
                    location_id=lot.location_id,
                    location_code=lot.location_code,
                    quantity=lot.quantity,
                )
                for lot in held.reserved
            ],
            consumed=held.consumed,
            units=[
                HeldUnitResponse(
                    unit_id=unit.unit_id, code=unit.code, location_code=unit.location_code
                )
                for unit in held.units
            ],
        )


class LifecycleResponse(BaseModel):
    """A revision's build: its status, the transitions it allows, whether it can be deleted,
    and each part it holds (requirement 10.1)."""

    status: RevisionStatusName
    transitions: list[TransitionName]
    deletable: bool
    parts: list[HeldPartResponse]

    @classmethod
    def from_lifecycle(cls, lifecycle: Lifecycle) -> Self:
        return cls(
            status=_status_name(lifecycle.status),
            transitions=[_transition_name(transition) for transition in lifecycle.transitions],
            deletable=lifecycle.deletable,
            parts=[HeldPartResponse.from_held(part) for part in lifecycle.parts],
        )


class RevisionRefResponse(BaseModel):
    """A revision found by its id alone, enough to name it and link to its project (10.2)."""

    id: UUID
    label: str
    summary: str | None
    status: RevisionStatusName
    project_id: UUID
    project_name: str

    @classmethod
    def from_ref(cls, ref: RevisionRef) -> Self:
        return cls(
            id=ref.revision_id,
            label=str(ref.label),
            summary=_text(ref.summary),
            status=_status_name(ref.status),
            project_id=ref.project_id,
            project_name=str(ref.project_name),
        )


class PartHoldingResponse(BaseModel):
    """One revision holding a part, with its ref, how many it reserves and how many its build
    consumed (requirement 10.4)."""

    revision: RevisionRefResponse
    reserved: int
    consumed: int

    @classmethod
    def from_view(cls, view: PartHoldingView) -> Self:
        return cls(
            revision=RevisionRefResponse.from_ref(view.revision),
            reserved=view.reserved,
            consumed=view.consumed,
        )


class LifecycleRefusalResponse(BaseModel):
    """The `detail` of a refused transition (decision 14).

    The sentence stays English; `code` is what the web translates. `status` is filled in for
    `transition_not_allowed`, `unit_id` and `unit_code` for the five unit refusals (the code
    only when the workspace holds the unit), and `report` for `short`.
    """

    message: str
    code: RefusalCode
    transition: TransitionName
    status: RevisionStatusName | None
    unit_id: UUID | None
    unit_code: str | None
    report: ShortageReportResponse | None

    @classmethod
    def from_refusal(cls, error: LifecycleRefusal) -> Self:
        status = error.status if isinstance(error, TransitionNotAllowedError) else None
        report = error.report if isinstance(error, ShortError) else None
        # `code` is one of the ten the union lists; the wire-names test keeps them in step, so
        # a new refusal without a matching literal is caught there rather than silently cast.
        code = cast(RefusalCode, error.code)
        return cls(
            message=str(error),
            code=code,
            transition=_transition_name(error.transition),
            status=None if status is None else _status_name(status),
            unit_id=getattr(error, "unit_id", None),
            unit_code=getattr(error, "unit_code", None),
            report=None if report is None else ShortageReportResponse.from_report(report),
        )


def _transition_name(transition: Transition) -> TransitionName:
    # An enum's value is the literal it holds, so a fifth transition stops type-checking here
    # until the wire contract above lists it too.
    name: TransitionName = transition.value
    return name


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


# --- The netlist (11-netlist-editor) ----------------------------------------------------------

# Spelled out for the wire like the statuses above: the web picks a swatch, a sentence and a
# marker per value, typed against these unions, so none ships without one. Tests keep each in
# step with its enum.
type WireColorName = Literal[
    "black", "brown", "red", "orange", "yellow", "green", "blue", "violet", "grey", "white"
]
type ResolutionName = Literal[
    "resolved", "unchecked", "unknown_designator", "unknown_part", "unknown_pin"
]
type PinTypeName = Literal["power", "ground", "io", "input", "output", "analog", "nc", "other"]
type NetFieldName = Literal["name", "color", "notes", "pins"]
type NetRefusalCodeName = Literal[
    "invalid_net_name",
    "net_name_taken",
    "invalid_notes",
    "invalid_pin_ref",
    "unknown_designator",
    "unknown_part",
    "unknown_pin",
    "ambiguous_pin",
    "repeated_pin",
    "no_pins",
    "too_many_pins",
    "too_many_nets",
    "revision_locked",
]


class NetRequest(BaseModel):
    """A net to add, or the whole of a net being edited (requirement 1.9). The pins are a list
    as typed, `U1.25, U2.SDA R1.2`, as a BOM line's designators are (decision 12)."""

    name: str = Field(max_length=MAX_TYPED_LENGTH)
    color: WireColorName | None = None
    notes: str | None = Field(default=None, max_length=MAX_TYPED_LENGTH)
    pins: str = Field(max_length=MAX_TYPED_LENGTH)


class NetlistPinResponse(BaseModel):
    """One pin of a part's pinout, as the editor offers it."""

    number: str
    label: str
    type: PinTypeName
    functions: list[str]
    voltage: str | None  # exact, as catalog's pinout API sends it

    @classmethod
    def from_pin(cls, pin: PinFacts) -> Self:
        return cls(
            number=str(pin.number),
            label=pin.label,
            type=_pin_type_name(pin.type),
            functions=list(pin.functions),
            voltage=_volts(pin.voltage),
        )


class NetPinResponse(BaseModel):
    """One reference of a net and what it resolves to at this read (requirement 4.1)."""

    ref: str
    designator: str
    pin: str
    resolution: ResolutionName
    part_id: UUID | None
    part_name: str | None
    label: str | None
    type: PinTypeName | None
    voltage: str | None

    @classmethod
    def from_resolution(cls, resolution: Resolution) -> Self:
        reference, part, pin = resolution.reference, resolution.part, resolution.pin
        state: ResolutionName = resolution.state.value
        return cls(
            ref=str(reference),
            designator=str(reference.designator),
            pin=str(reference.pin),
            resolution=state,
            part_id=None if part is None else part.part_id,
            part_name=None if part is None else part.name,
            label=None if pin is None else pin.label,
            type=None if pin is None else _pin_type_name(pin.type),
            voltage=None if pin is None else _volts(pin.voltage),
        )


class NetResponse(BaseModel):
    """A net with its references in canonical order, each resolved (requirement 1.11)."""

    id: UUID
    name: str
    color: WireColorName | None
    notes: str | None
    pins: list[NetPinResponse]
    pins_text: str

    @classmethod
    def from_net(cls, net: Net, view: NetlistView) -> Self:
        content = net.content
        color: WireColorName | None = None if content.color is None else content.color.value
        return cls(
            id=net.id,
            name=str(content.name),
            color=color,
            notes=None if content.notes is None else str(content.notes),
            pins=[
                NetPinResponse.from_resolution(view.resolution(reference))
                for reference in content.pins
            ],
            pins_text=content.pins.text(),
        )


class BomDesignatorResponse(BaseModel):
    """A designator on the BOM and its part; no name when the catalog no longer holds it."""

    designator: str
    part_id: UUID
    part_name: str | None


class NetlistPartResponse(BaseModel):
    """A part on the BOM the catalog holds, with its pins in their saved order (7.2)."""

    part_id: UUID
    name: str
    has_pinout: bool
    pins: list[NetlistPinResponse]


class NetlistSummaryResponse(BaseModel):
    nets: int
    references: int
    unchecked: int
    unresolved: int


class NetlistResponse(BaseModel):
    """A revision's netlist, its summary, and what the editor picks from (4, 5.2, 7)."""

    editable: bool
    nets: list[NetResponse]
    summary: NetlistSummaryResponse
    designators: list[BomDesignatorResponse]
    parts: list[NetlistPartResponse]

    @classmethod
    def from_view(cls, view: NetlistView) -> Self:
        summary = view.summary()
        designators = sorted(
            (designator, line.content.part_id)
            for line in view.bom.lines
            for designator in line.content.designators
        )
        return cls(
            editable=view.editable,
            nets=[NetResponse.from_net(net, view) for net in view.netlist.nets],
            summary=NetlistSummaryResponse(
                nets=summary.nets,
                references=summary.references,
                unchecked=summary.unchecked,
                unresolved=summary.unresolved,
            ),
            designators=[
                BomDesignatorResponse(
                    designator=str(designator),
                    part_id=part_id,
                    part_name=_part_name(view, part_id),
                )
                for designator, part_id in designators
            ],
            parts=[
                NetlistPartResponse(
                    part_id=part_id,
                    name=view.parts[part_id].name,
                    has_pinout=part_id in view.pins,
                    pins=[NetlistPinResponse.from_pin(pin) for pin in _pins_of(view, part_id)],
                )
                for part_id in view.bom.part_ids()
                if part_id in view.parts
            ],
        )


class NetRefusalResponse(BaseModel):
    """The `detail` of a refused net write (design's Error Handling).

    The sentence stays English; the code is what the web translates, and the field is where the
    editor shows it. `item` is the reference or text as typed; an ambiguous pin carries the
    numbers it could be, and a taken name the net holding it.
    """

    message: str
    code: NetRefusalCodeName
    field: NetFieldName | None
    item: str | None
    candidates: list[str]
    net_id: UUID | None
    net: str | None

    @classmethod
    def from_error(cls, error: NetError) -> Self:
        code: NetRefusalCodeName = error.code.value
        field: NetFieldName | None = None if error.field is None else error.field.value
        taken = error if isinstance(error, NetNameTakenError) else None
        ambiguous = error if isinstance(error, AmbiguousPinError) else None
        return cls(
            message=str(error),
            code=code,
            field=field,
            item=error.item,
            candidates=[] if ambiguous is None else list(ambiguous.candidates),
            net_id=None if taken is None else taken.net_id,
            net=None if taken is None else taken.net,
        )

    @classmethod
    def locked(cls, error: RevisionContentLockedError) -> Self:
        """A write to a revision that isn't a draft: the BOM's refusal, in the netlist's words."""
        return cls(
            message=str(error),
            code="revision_locked",
            field=None,
            item=None,
            candidates=[],
            net_id=None,
            net=None,
        )


def _pin_type_name(kind: PinType) -> PinTypeName:
    name: PinTypeName = kind.value
    return name


def _volts(voltage: Decimal | None) -> str | None:
    # Plain digits, never 1E+3, as catalog's pinout API writes a level.
    return None if voltage is None else f"{voltage:f}"


def _part_name(view: NetlistView, part_id: PartId) -> str | None:
    part = view.parts.get(part_id)
    return None if part is None else part.name


def _pins_of(view: NetlistView, part_id: PartId) -> tuple[PinFacts, ...]:
    pins = view.pins.get(part_id)
    return () if pins is None else pins.pins
