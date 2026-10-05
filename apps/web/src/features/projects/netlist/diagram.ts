import type { Net, NetPin, WireColor } from "@wiredex/api-client";

/** The diagram's measures, in the SVG's own units (CSS pixels at its natural size). */
export const DIAGRAM = {
  partWidth: 210,
  header: 46,
  row: 24,
  /** The channel the wires cross, between the hub and the parts wired to it. */
  channel: 240,
  gap: 20,
  margin: 12,
  /** How far a wire between two pins of one column bows out of it. */
  bow: 56,
} as const;

export type DiagramPin = {
  ref: string;
  pin: string;
  label: string | null;
  /** Whether the pin was found on its part's pinout, or left unchecked for want of one. */
  known: boolean;
  /** Where its wires land: on the part's edge that faces the channel. */
  x: number;
  y: number;
};

export type DiagramPart = {
  designator: string;
  name: string | null;
  /** The hub sits left of the channel, its pins on its right edge; every other part faces it. */
  side: "left" | "right";
  x: number;
  y: number;
  width: number;
  height: number;
  pins: DiagramPin[];
};

export type DiagramWire = {
  key: string;
  net: string;
  color: WireColor | null;
  from: string;
  to: string;
  path: string;
};

export type DiagramLabel = {
  key: string;
  net: string;
  x: number;
  y: number;
  anchor: "start" | "end";
};

export type Diagram = {
  width: number;
  height: number;
  parts: DiagramPart[];
  wires: DiagramWire[];
  labels: DiagramLabel[];
};

const byNumber = new Intl.Collator("en", { numeric: true });

/**
 * Lays a revision's nets out as a drawing: the part with the most wired pins is the hub, on the
 * left, and every other part stacks on the right, facing it, in the order of the hub pins it is
 * wired to, so few wires cross. A part shows only its wired pins, in pin order. A net is drawn
 * from one pin, the hub's when it has one, to each of its others: a curve across the channel,
 * or a bow beside the column when both pins are on the same side. Nothing here measures the
 * page: the same nets always give the same drawing.
 */
export function layoutDiagram(nets: readonly Net[]): Diagram {
  const pinsOf = new Map<string, Map<string, NetPin>>();
  for (const net of nets)
    for (const pin of net.pins) {
      const pins = pinsOf.get(pin.designator) ?? new Map<string, NetPin>();
      if (!pins.has(pin.ref)) pins.set(pin.ref, pin);
      pinsOf.set(pin.designator, pins);
    }
  if (pinsOf.size === 0) return { width: 0, height: 0, parts: [], wires: [], labels: [] };

  const designators = [...pinsOf.keys()];
  const hub = designators.reduce((most, next) =>
    (pinsOf.get(next)?.size ?? 0) > (pinsOf.get(most)?.size ?? 0) ? next : most,
  );
  const sorted = (designator: string) =>
    [...(pinsOf.get(designator)?.values() ?? [])].sort((a, b) => byNumber.compare(a.pin, b.pin));
  const hubRow = new Map(sorted(hub).map((pin, row) => [pin.ref, row]));

  // A part sits level with the hub pins it is wired to: the mean of their rows, last without any.
  const level = (designator: string) => {
    const rows = nets
      .filter((net) => net.pins.some((pin) => pin.designator === designator))
      .flatMap((net) => net.pins.map((pin) => hubRow.get(pin.ref)))
      .filter((row) => row !== undefined);
    return rows.length ? rows.reduce((sum, row) => sum + row, 0) / rows.length : Infinity;
  };
  const others = designators
    .filter((designator) => designator !== hub)
    .map((designator) => ({ designator, level: level(designator) }))
    .sort((a, b) => a.level - b.level || byNumber.compare(a.designator, b.designator))
    .map((other) => other.designator);

  const heightOf = (designator: string) =>
    DIAGRAM.header + (pinsOf.get(designator)?.size ?? 0) * DIAGRAM.row + DIAGRAM.row / 2;
  const rightX = DIAGRAM.margin + DIAGRAM.bow + DIAGRAM.partWidth + DIAGRAM.channel;
  const place = (designator: string, side: "left" | "right", y: number): DiagramPart => {
    const x = side === "left" ? DIAGRAM.margin + DIAGRAM.bow : rightX;
    const pins = sorted(designator);
    return {
      designator,
      name: pins.find((pin) => pin.part_name)?.part_name ?? null,
      side,
      x,
      y,
      width: DIAGRAM.partWidth,
      height: heightOf(designator),
      pins: pins.map((pin, row) => ({
        ref: pin.ref,
        pin: pin.pin,
        label: pin.label ?? null,
        known: pin.resolution === "resolved" || pin.resolution === "unchecked",
        x: side === "left" ? x + DIAGRAM.partWidth : x,
        y: y + DIAGRAM.header + row * DIAGRAM.row + DIAGRAM.row / 2,
      })),
    };
  };

  const stack = others.reduce((sum, other) => sum + heightOf(other) + DIAGRAM.gap, -DIAGRAM.gap);
  const inner = Math.max(heightOf(hub), stack);
  const parts = [place(hub, "left", DIAGRAM.margin + (inner - heightOf(hub)) / 2)];
  let y = DIAGRAM.margin + (inner - Math.max(stack, 0)) / 2;
  for (const other of others) {
    parts.push(place(other, "right", y));
    y += heightOf(other) + DIAGRAM.gap;
  }

  const at = new Map(
    parts.flatMap((part) => part.pins.map((pin) => [pin.ref, { ...pin, side: part.side }])),
  );
  const wires: DiagramWire[] = [];
  const labels: DiagramLabel[] = [];
  for (const net of nets) {
    const refs = [...new Set(net.pins.map((pin) => pin.ref))];
    const start = refs.find((ref) => hubRow.has(ref)) ?? refs[0];
    const from = start === undefined ? undefined : at.get(start);
    if (!from) continue;
    // The net's name reads beside the pin its wires leave from, on the channel's side.
    const out = from.side === "left" ? 1 : -1;
    labels.push({
      key: net.id,
      net: net.name,
      x: from.x + out * 8,
      y: from.y - 5,
      anchor: from.side === "left" ? "start" : "end",
    });
    for (const ref of refs) {
      const to = at.get(ref);
      if (!to || ref === start) continue;
      wires.push({
        key: `${net.id}:${ref}`,
        net: net.name,
        color: net.color ?? null,
        from: from.ref,
        to: to.ref,
        path: wirePath(from, to, from.side === to.side ? out : 0),
      });
    }
  }

  const single = others.length === 0;
  return {
    width:
      (single ? DIAGRAM.margin + DIAGRAM.bow + DIAGRAM.partWidth : rightX + DIAGRAM.partWidth) +
      DIAGRAM.bow +
      DIAGRAM.margin,
    height: inner + 2 * DIAGRAM.margin,
    parts,
    wires,
    labels,
  };
}

type Point = { x: number; y: number };

/**
 * A wire as an SVG path. Across the channel it leaves and arrives level, so it reads at both
 * pins; between two pins of one column it bows out by BOWING's sign, further the further apart
 * the pins are, so two such wires don't lie on each other.
 */
function wirePath(from: Point, to: Point, bowing: number): string {
  if (bowing === 0) {
    const reach = Math.abs(to.x - from.x) / 2;
    const toward = Math.sign(to.x - from.x);
    return `M ${from.x} ${from.y} C ${from.x + toward * reach} ${from.y}, ${to.x - toward * reach} ${to.y}, ${to.x} ${to.y}`;
  }
  const depth = Math.min(DIAGRAM.bow, 24 + Math.abs(to.y - from.y) / 6) * 1.3;
  const x = from.x + bowing * depth;
  return `M ${from.x} ${from.y} C ${x} ${from.y}, ${x} ${to.y}, ${to.x} ${to.y}`;
}
