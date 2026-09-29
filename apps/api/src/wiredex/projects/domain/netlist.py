"""A revision's netlist: its nets, the pin references they connect, and what those resolve to.

A pin reference is a BOM designator and a pin number, stored as text with no foreign key
(decision 2), so a BOM or pinout edit never blocks and never deletes wiring. What it names is
worked out at every read, `Resolution.of`, from the BOM, the catalog and the pinouts as they
stand then (decision 3); a write accepts a new reference only when it names a real pin
(decision 4).
"""

import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from wiredex.projects.domain.bom import BillOfMaterials
from wiredex.projects.domain.designators import Designator
from wiredex.projects.domain.errors import (
    AmbiguousPinError,
    InvalidDesignatorError,
    InvalidNetNameError,
    InvalidNetNotesError,
    InvalidPinReferenceError,
    NetNameTakenError,
    NetNotFoundError,
    NoPinsError,
    RepeatedPinError,
    TooManyNetsError,
    TooManyPinsError,
    UnknownDesignatorError,
    UnknownNetPartError,
    UnknownPinError,
)
from wiredex.projects.domain.pins import PartPins, PinFacts, PinNumber
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.shortage import PartFacts
from wiredex.projects.domain.values import NetId, PartId, RevisionId, WorkspaceId

MAX_NETS = 500  # on one revision
MAX_NET_PINS = 256  # on one net
MAX_NET_NAME_LENGTH = 32
MAX_NET_NOTES_LENGTH = 500

_SEPARATORS = re.compile(r"[,\s]+")


@dataclass(frozen=True, slots=True)
class PinReference:
    """A stored reference: a designator and the pin number it names (decision 2)."""

    designator: Designator
    pin: PinNumber

    def sort_key(self) -> tuple[Designator, tuple[tuple[tuple[int, int, str], ...], str]]:
        """Decision 8's order: by designator as 09 orders them, then by the pin's natural key."""
        return self.designator, self.pin.sort_key()

    def __str__(self) -> str:
        return f"{self.designator}.{self.pin}"


@dataclass(frozen=True, slots=True)
class TypedReference:
    """A reference as typed, split at its first dot (requirement 2.1): a designator and the
    pin's text, not yet a number. A designator never holds a dot (09's decision 5); a pin number
    may (`P1.3`), which is why the split is at the first one."""

    text: str
    designator: Designator
    pin: str

    @classmethod
    def parse(cls, text: str) -> TypedReference:
        """NFKC and trimmed, then `<designator>.<pin>`; `InvalidPinReferenceError` naming the
        text for no dot, a left half that isn't a designator, or an empty pin."""
        cleaned = unicodedata.normalize("NFKC", text).strip()
        left, dot, right = cleaned.partition(".")
        pin = right.strip()
        if not dot or not pin:
            raise _not_a_reference(text)
        try:
            designator = Designator.parse(left)
        except InvalidDesignatorError as error:
            raise _not_a_reference(text) from error
        return cls(text, designator, pin)

    def as_stored(self) -> PinReference | None:
        """The stored reference this spelling would be if its pin were taken as a number, or
        None when the pin isn't one: how an edit recognizes a reference its net already holds
        (requirement 3.8) without looking at the BOM or a pinout."""
        if not PinNumber.is_one(self.pin):
            return None
        return PinReference(self.designator, PinNumber(self.pin))

    def resolve(
        self,
        bom: BillOfMaterials,
        parts: Mapping[PartId, PartFacts],
        pins: Mapping[PartId, PartPins],
    ) -> PinReference:
        """The stored reference this new one names, or a refusal naming it as typed (decision 4).

        The designator's line gives the part; a part with a pinout is matched by number, then
        by label, then by function, and stored by the number it matched; a part with none takes
        the pin as a number, unchecked.
        """
        line = bom.line_with(self.designator)
        if line is None:
            raise UnknownDesignatorError(
                f"{self.text}: {self.designator} isn't on this revision's BOM", item=self.text
            )
        part = parts.get(line.content.part_id)
        if part is None:
            raise UnknownNetPartError(
                f"{self.text}: the part on {self.designator} isn't in the catalog any more",
                item=self.text,
            )
        pinout = pins.get(part.part_id)
        if pinout is None:
            return self._unchecked()
        return PinReference(self.designator, self._matched(pinout, part).number)

    def _unchecked(self) -> PinReference:
        try:
            return PinReference(self.designator, PinNumber(self.pin))
        except InvalidPinReferenceError as error:
            raise InvalidPinReferenceError(
                f"{self.text}: the part on {self.designator} has no pinout, so its pins are "
                "named by number, like 1 or A1",
                item=self.text,
            ) from error

    def _matched(self, pinout: PartPins, part: PartFacts) -> PinFacts:
        found = pinout.matching(self.pin)
        if not found:
            raise UnknownPinError(f"{self.text}: {part.name} has no pin {self.pin}", item=self.text)
        if len(found) > 1:
            numbers = tuple(str(pin.number) for pin in found)
            raise AmbiguousPinError(
                f"{self.text} could be pins {_listed(numbers)} of {part.name}; name one by number",
                item=self.text,
                candidates=numbers,
            )
        return found[0]


def parse_pin_list(text: str) -> tuple[TypedReference, ...]:
    """Items separated by commas or whitespace, each one pin reference (requirement 2.2)."""
    normalized = unicodedata.normalize("NFKC", text)
    return tuple(TypedReference.parse(item) for item in _SEPARATORS.split(normalized) if item)


@dataclass(frozen=True, slots=True)
class NetName:
    """What the owner calls a net: `SDA`, `3V3`, `SOIL_ADC`. Trimmed, whitespace collapsed,
    1 to 32 characters and no control character; its case is kept (decision 6)."""

    value: str

    def __post_init__(self) -> None:
        name = " ".join(self.value.split())
        if not 1 <= len(name) <= MAX_NET_NAME_LENGTH or not name.isprintable():
            raise InvalidNetNameError(
                f"a net name needs between 1 and {MAX_NET_NAME_LENGTH} printable characters",
                item=self.value,
            )
        object.__setattr__(self, "value", name)

    def fold(self) -> str:
        """What uniqueness compares: lower(), the unique index's own expression, as 08's
        project names fold."""
        return self.value.lower()

    def __str__(self) -> str:
        return self.value


class WireColor(StrEnum):
    """The ten colors of the resistor code, the ones jumper kits come in (decision 7)."""

    BLACK = "black"
    BROWN = "brown"
    RED = "red"
    ORANGE = "orange"
    YELLOW = "yellow"
    GREEN = "green"
    BLUE = "blue"
    VIOLET = "violet"
    GREY = "grey"
    WHITE = "white"


@dataclass(frozen=True, slots=True)
class NetNotes:
    """A net's note: trimmed, whitespace collapsed, 1 to 500 characters, as a BOM line's is.
    Blank text is no note, which the edge reads as None before it gets here."""

    value: str

    def __post_init__(self) -> None:
        collapsed = " ".join(self.value.split())
        if not 1 <= len(collapsed) <= MAX_NET_NOTES_LENGTH:
            raise InvalidNetNotesError(
                f"a net's notes need between 1 and {MAX_NET_NOTES_LENGTH} characters"
            )
        object.__setattr__(self, "value", collapsed)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class NetPins:
    """A net's references: at least one, at most 256, each once, in canonical order.

    Checked and sorted here rather than only where a write builds them, so no path holds a pin
    twice and two spellings of one net compare equal (decision 8).
    """

    values: tuple[PinReference, ...]

    def __post_init__(self) -> None:
        seen: set[PinReference] = set()
        for reference in self.values:
            if reference in seen:
                raise RepeatedPinError(f"{reference} is already on this net", item=str(reference))
            seen.add(reference)
        if not seen:
            raise NoPinsError("a net needs at least one pin")
        if len(seen) > MAX_NET_PINS:
            raise TooManyPinsError(f"a net connects at most {MAX_NET_PINS} pins")
        object.__setattr__(self, "values", tuple(sorted(seen, key=PinReference.sort_key)))

    @classmethod
    def of(cls, references: Iterable[PinReference]) -> NetPins:
        return cls(tuple(references))

    def text(self) -> str:
        """The canonical text: `U1.2, U1.10, U2.3` (requirement 2.5)."""
        return ", ".join(str(reference) for reference in self.values)

    def __iter__(self) -> Iterator[PinReference]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)


@dataclass(frozen=True, slots=True)
class NetContent:
    """What a net says, and everything an edit replaces (requirement 1.9)."""

    name: NetName
    color: WireColor | None
    notes: NetNotes | None
    pins: NetPins


@dataclass(frozen=True, slots=True)
class Net:
    """One net of a revision. Immutable, as 09's `BomLine` is: an edit is a new value with the
    same id, which is what lets the repository tell a no-op from a change."""

    id: NetId
    workspace_id: WorkspaceId
    revision_id: RevisionId
    content: NetContent
    created_at: datetime

    @classmethod
    def on(cls, revision: Revision, net_id: NetId, content: NetContent, now: datetime) -> Net:
        """A new net of the revision: its workspace and revision come from the revision."""
        return cls(net_id, revision.workspace_id, revision.id, content, now)

    def revised(self, content: NetContent) -> Net:
        return replace(self, content=content)

    def copied_to(self, target: Revision, net_id: NetId) -> Net:
        """The same content on a fork, created with it (decision 10): the fork's date and ids
        minted in the source's order keep the copies in the source's order."""
        return Net(net_id, target.workspace_id, target.id, self.content, target.created_at)


@dataclass(frozen=True, slots=True)
class Netlist:
    """One revision's nets, oldest first, as the repository reads them. Its rules: at most 500
    nets, and no two names equal ignoring case. A pin may sit in several nets: *pin reused* is
    a finding of 12's rules, not a refusal here (decision 5)."""

    revision_id: RevisionId
    nets: tuple[Net, ...] = ()

    def with_net(self, net: Net) -> Netlist:
        """The net after the others: `TooManyNetsError` for a 501st, `NetNameTakenError` naming
        the net that holds the name."""
        if len(self.nets) >= MAX_NETS:
            raise TooManyNetsError(f"a revision's netlist holds at most {MAX_NETS} nets")
        self._ensure_free(net)
        return replace(self, nets=(*self.nets, net))

    def replacing(self, net: Net) -> Netlist:
        """The net's new value in its place; its own name doesn't count against it."""
        self.net(net.id)
        self._ensure_free(net)
        return replace(self, nets=tuple(net if held.id == net.id else held for held in self.nets))

    def without(self, net_id: NetId) -> Netlist:
        self.net(net_id)
        return replace(self, nets=tuple(held for held in self.nets if held.id != net_id))

    def net(self, net_id: NetId) -> Net:
        """`NetNotFoundError` for a net that isn't on this netlist, another revision's
        included (requirement 1.12)."""
        for held in self.nets:
            if held.id == net_id:
                return held
        raise NetNotFoundError("that net isn't on this revision's netlist")

    def references(self) -> frozenset[PinReference]:
        return frozenset(reference for held in self.nets for reference in held.content.pins)

    def _ensure_free(self, net: Net) -> None:
        folded = net.content.name.fold()
        for held in self.nets:
            if held.id != net.id and held.content.name.fold() == folded:
                raise NetNameTakenError(
                    f"the net {held.content.name} already has that name",
                    item=str(net.content.name),
                    net_id=held.id,
                    net=str(held.content.name),
                )


def _not_a_reference(text: str) -> InvalidPinReferenceError:
    return InvalidPinReferenceError(
        f"{text!r} is not a pin reference like U1.21 or U2.SDA: a designator, a dot and a pin",
        item=text,
    )


def _listed(numbers: Sequence[str]) -> str:
    """`14, 20 or 26`, as the refusal says it."""
    if len(numbers) == 1:
        return numbers[0]
    return f"{', '.join(numbers[:-1])} or {numbers[-1]}"


class ResolutionState(StrEnum):
    """What a stored reference names today (decision 3)."""

    RESOLVED = "resolved"  # the part's pinout holds its number
    UNCHECKED = "unchecked"  # the part has no pinout
    UNKNOWN_DESIGNATOR = "unknown_designator"  # no BOM line holds its designator
    UNKNOWN_PART = "unknown_part"  # the line names a part the catalog no longer holds
    UNKNOWN_PIN = "unknown_pin"  # the part's pinout has no such number

    @property
    def unresolved(self) -> bool:
        return self in _UNRESOLVED


_UNRESOLVED = frozenset(
    {
        ResolutionState.UNKNOWN_DESIGNATOR,
        ResolutionState.UNKNOWN_PART,
        ResolutionState.UNKNOWN_PIN,
    }
)


@dataclass(frozen=True, slots=True)
class Resolution:
    """What a stored reference names at this read, computed and never stored (decision 3)."""

    reference: PinReference
    state: ResolutionState
    part: PartFacts | None = None  # the designator's part, when on the BOM and in the catalog
    pin: PinFacts | None = None  # when resolved

    @classmethod
    def of(
        cls,
        reference: PinReference,
        bom: BillOfMaterials,
        parts: Mapping[PartId, PartFacts],
        pins: Mapping[PartId, PartPins],
    ) -> Resolution:
        line = bom.line_with(reference.designator)
        if line is None:
            return cls(reference, ResolutionState.UNKNOWN_DESIGNATOR)
        part = parts.get(line.content.part_id)
        if part is None:
            return cls(reference, ResolutionState.UNKNOWN_PART)
        pinout = pins.get(part.part_id)
        if pinout is None:
            return cls(reference, ResolutionState.UNCHECKED, part)
        pin = pinout.numbered(reference.pin)
        if pin is None:
            return cls(reference, ResolutionState.UNKNOWN_PIN, part)
        return cls(reference, ResolutionState.RESOLVED, part, pin)


@dataclass(frozen=True, slots=True)
class NetDraft:
    """A net as a write sends it, its text read into values before anything is read from the
    database (requirement 1): the name, color and notes checked, the pins split into typed
    references. `content` finishes it against the BOM and the pinouts."""

    name: NetName
    color: WireColor | None
    notes: NetNotes | None
    typed: tuple[TypedReference, ...]

    @classmethod
    def parse(cls, name: str, color: str | None, notes: str | None, pins: str) -> NetDraft:
        typed = parse_pin_list(pins)
        if not typed:
            raise NoPinsError("a net needs at least one pin")
        return cls(
            NetName(name),
            None if color is None else WireColor(color),
            None if notes is None or not notes.strip() else NetNotes(notes),
            typed,
        )

    def new_references(self, kept: frozenset[PinReference]) -> tuple[TypedReference, ...]:
        """The typed references that aren't one the net already held: only these are resolved,
        so only their designators' parts are read."""
        return tuple(item for item in self.typed if item.as_stored() not in kept)

    def content(
        self,
        bom: BillOfMaterials,
        parts: Mapping[PartId, PartFacts],
        pins: Mapping[PartId, PartPins],
        kept: frozenset[PinReference] = frozenset(),
    ) -> NetContent:
        """Each typed reference the net already held taken as stored, whatever it resolves to
        now (requirement 3.8); every other one resolved, or refused naming it as typed; then a
        pin twice refused naming the second spelling (requirement 2.4)."""
        stored: dict[PinReference, TypedReference] = {}
        for item in self.typed:
            held = item.as_stored()
            if held is not None and held in kept:
                reference = held
            else:
                reference = item.resolve(bom, parts, pins)
            if reference in stored:
                raise RepeatedPinError(
                    f"{item.text} is the same pin as {stored[reference].text}", item=item.text
                )
            stored[reference] = item
        return NetContent(self.name, self.color, self.notes, NetPins.of(stored))
