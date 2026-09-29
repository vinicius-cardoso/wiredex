"""A revision's netlist: its nets, the pin references they connect, and what those resolve to.

A pin reference is a BOM designator and a pin number, stored as text with no foreign key
(decision 2), so a BOM or pinout edit never blocks and never deletes wiring. What it names is
worked out at every read, `Resolution.of`, from the BOM, the catalog and the pinouts as they
stand then (decision 3); a write accepts a new reference only when it names a real pin
(decision 4).
"""

import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from wiredex.projects.domain.designators import Designator
from wiredex.projects.domain.errors import (
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
)
from wiredex.projects.domain.pins import PinNumber
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import NetId, RevisionId, WorkspaceId

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
