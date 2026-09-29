"""Hypothesis strategies for pin references, nets and netlists, shared by the netlist tests.

References draw their designators and pins from small pools, so that nets share pins and
names clash: independent draws would almost never repeat, and the rules about repeats would go
untested.
"""

import string
from datetime import UTC, datetime
from uuid import uuid7

from hypothesis import strategies as st

from wiredex.projects.domain.designators import Designator
from wiredex.projects.domain.netlist import (
    Net,
    NetContent,
    NetName,
    NetNotes,
    NetPins,
    PinReference,
    WireColor,
)
from wiredex.projects.domain.pins import PinNumber
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import NetId

DESIGNATOR_POOL = tuple(Designator(letters, number) for letters in ("R", "U") for number in (1, 2))
PIN_POOL = tuple(PinNumber(text) for text in ("1", "2", "10", "A1", "SDA"))

pin_numbers = st.text(string.ascii_uppercase + string.digits + "_.+-", min_size=1, max_size=16).map(
    PinNumber
)
references = st.builds(PinReference, st.sampled_from(DESIGNATOR_POOL), st.sampled_from(PIN_POOL))
net_names = st.sampled_from(["SDA", "sda", "SCL", "3V3", "GND", "gnd"]).map(NetName)
wire_colors = st.none() | st.sampled_from(WireColor)
net_notes = st.none() | st.just(NetNotes("probe divider midpoint"))


@st.composite
def net_pins(draw: st.DrawFn) -> NetPins:
    return NetPins.of(draw(st.sets(references, min_size=1, max_size=6)))


net_contents = st.builds(NetContent, net_names, wire_colors, net_notes, net_pins())

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


def a_net(revision: Revision, content: NetContent, net_id: NetId | None = None) -> Net:
    return Net.on(revision, net_id or NetId(uuid7()), content, NOW)


def content_of(name: str, *pins: str, color: WireColor | None = None) -> NetContent:
    """A net's content from text, `content_of("SDA", "U1.25", "R1.2")`."""
    parsed = []
    for text in pins:
        designator, _, pin = text.partition(".")
        parsed.append(PinReference(Designator.parse(designator), PinNumber(pin)))
    return NetContent(NetName(name), color, None, NetPins.of(parsed))
