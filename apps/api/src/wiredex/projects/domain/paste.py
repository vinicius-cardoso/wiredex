"""Pasting wiring: several lines taken as one change to a netlist (22: the netlist's paste).

Each line is a connection, some pins to be made common, with a name or without. Where it lands
is read off the netlist as the lines before it left it:

- pins none of which is on a net make a new net, named as the line says, or after the role of
  one of its pins when it names none;
- a pin already on a net takes the line's other pins to that net, which is what connecting to
  it means, and what keeps a pin off two nets;
- a name a net already has takes the line's pins to that net.

A line that would join two nets, or that names a net while one of its pins is on another, is
refused: which of the two was meant is the owner's to say. A refusal carries the line's
number, and the whole paste is refused with it, so a netlist is never half pasted.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from wiredex.projects.domain.bom import BillOfMaterials
from wiredex.projects.domain.errors import (
    JoinsTwoNetsError,
    NamedOtherwiseError,
    NetError,
    NoPinsError,
)
from wiredex.projects.domain.netlist import (
    MAX_NET_NAME_LENGTH,
    Net,
    NetContent,
    Netlist,
    NetName,
    NetNotes,
    NetPins,
    PinReference,
    TypedReference,
    WireColor,
    parse_pin_list,
)
from wiredex.projects.domain.pins import PartPins
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.shortage import PartFacts
from wiredex.projects.domain.values import NetId, PartId

#: More lines than any board's wiring typed at once; past it the paste is a mistake.
MAX_PASTED_ROWS = 500


@dataclass(frozen=True, slots=True)
class PastedRow:
    """One line as it was pasted: its pins as typed, and what it said of the net."""

    pins: str
    name: str | None = None
    color: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class Board:
    """What a line's pins are read against: the revision's BOM, and the catalog's word on the
    parts on it and their pinouts, read once for the whole paste."""

    bom: BillOfMaterials
    parts: Mapping[PartId, PartFacts]
    pins: Mapping[PartId, PartPins]


@dataclass(frozen=True, slots=True)
class Making:
    """What a new net is made with: its revision, where its id comes from, and the moment."""

    revision: Revision
    new_id: Callable[[], NetId]
    now: datetime


@dataclass(frozen=True, slots=True)
class Pasted:
    """A paste applied: the netlist it leaves, the nets it made, and the nets it changed, each
    as it was before and as it is after, for the repository to write."""

    netlist: Netlist
    added: tuple[Net, ...]
    changed: tuple[tuple[Net, Net], ...]


def paste_rows(netlist: Netlist, rows: Sequence[PastedRow], board: Board, making: Making) -> Pasted:
    """The netlist with every row applied in order, or the first refusal, carrying its row."""
    original = {net.id: net for net in netlist.nets}
    added: dict[NetId, Net] = {}
    for number, row in enumerate(rows, start=1):
        try:
            netlist = _apply(netlist, row, board, making, added)
        except NetError as error:
            error.row = number
            raise
    changed = tuple(
        (before, after)
        for before in original.values()
        if (after := netlist.net(before.id)) != before
    )
    return Pasted(netlist, tuple(netlist.net(net_id) for net_id in added), changed)


def _apply(
    netlist: Netlist, row: PastedRow, board: Board, making: Making, added: dict[NetId, Net]
) -> Netlist:
    typed = parse_pin_list(row.pins)
    if not typed:
        raise NoPinsError("a line needs at least one pin")
    # A pin written twice on a line is one pin: a paste isn't a form to be told off in.
    resolved = [(item, item.resolve(board.bom, board.parts, board.pins)) for item in typed]
    references = tuple(dict.fromkeys(reference for _, reference in resolved))
    named = None if row.name is None or not row.name.strip() else NetName(row.name)
    color = None if row.color is None or not row.color.strip() else WireColor(row.color.strip())
    notes = None if row.notes is None or not row.notes.strip() else NetNotes(row.notes)

    target = _target(netlist, named, references) or _suggested(resolved, board)
    held = target if isinstance(target, Net) else _named(netlist, target)
    if held is None:
        assert isinstance(target, NetName)  # noqa: S101 - a Net is always held
        content = NetContent(target, color, notes, NetPins.of(references))
        net = Net.on(making.revision, making.new_id(), content, making.now)
        added[net.id] = net
        return netlist.with_net(net)
    after = held.revised(
        NetContent(
            held.content.name,
            # A line never repaints a net: it only gives a colour to one that has none.
            held.content.color or color,
            held.content.notes or notes,
            NetPins.of(dict.fromkeys((*held.content.pins, *references))),
        )
    )
    if held.id in added:
        added[held.id] = after
    return netlist if after == held else netlist.replacing(after)


def _target(
    netlist: Netlist, named: NetName | None, references: Sequence[PinReference]
) -> Net | NetName | None:
    """The net the row's pins already reach, or the name the row gave; None for a row that
    reaches no net and names none, which is then named after one of its pins."""
    by_pin = _reached(netlist, references)
    if named is None:
        return None if by_pin is None else by_pin[0]
    if by_pin is not None and by_pin[0] is not _named(netlist, named):
        raise NamedOtherwiseError(
            f"{by_pin[1]} is already on {by_pin[0].content.name}, and this line names {named}",
            item=str(by_pin[1]),
        )
    return named


def _reached(
    netlist: Netlist, references: Sequence[PinReference]
) -> tuple[Net, PinReference] | None:
    """The one net a pin of the row is already on, with that pin; refused when there are two."""
    touched: dict[NetId, tuple[Net, PinReference]] = {}
    for reference in references:
        for held in netlist.nets:
            if reference in held.content.pins:
                touched.setdefault(held.id, (held, reference))
    if len(touched) > 1:
        (first, first_pin), (second, second_pin) = list(touched.values())[:2]
        raise JoinsTwoNetsError(
            f"{first_pin} is on {first.content.name} and {second_pin} on {second.content.name}:"
            " one line can't join two nets",
            item=str(second_pin),
        )
    return next(iter(touched.values()), None)


def _named(netlist: Netlist, name: NetName) -> Net | None:
    folded = name.fold()
    return next((held for held in netlist.nets if held.content.name.fold() == folded), None)


def _suggested(resolved: Sequence[tuple[TypedReference, PinReference]], board: Board) -> NetName:
    """A name for a line that gave none: the role one of its pins was typed by, `SDA` in
    `U2.SDA`; else the label a pinout gives one of them; else its two ends, `U1.25-U2.3`."""
    for item, reference in resolved:
        # Typed by a label or a function, not by the number it was stored as.
        if item.pin.strip().casefold() != str(reference.pin).casefold():
            return _fitted(item.pin.strip().upper())
    references = [reference for _, reference in resolved]
    for reference in references:
        line = board.bom.line_with(reference.designator)
        pinout = None if line is None else board.pins.get(line.content.part_id)
        pin = None if pinout is None else pinout.numbered(reference.pin)
        if pin is not None and pin.label.strip():
            return _fitted(pin.label)
    ends = (references[0], references[-1]) if len(references) > 1 else references
    return _fitted("-".join(str(reference) for reference in ends))


def _fitted(text: str) -> NetName:
    return NetName(" ".join(text.split())[:MAX_NET_NAME_LENGTH])
