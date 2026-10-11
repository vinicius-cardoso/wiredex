import type { Net, NetPin, WireColor } from "@wiredex/api-client";

/** The diagram's measures, in the SVG's own units (CSS pixels at its natural size). */
export const DIAGRAM = {
  partWidth: 210,
  header: 46,
  row: 24,
  /** The least width of the channel the wires run in, between the hub and the other parts. */
  channel: 240,
  /** The space between two nets' vertical runs in the channel. */
  track: 12,
  /** The least space between a part's edge and the nearest vertical run. */
  lead: 24,
  /** As much of a net's name as is drawn beside its pin. */
  labelLength: 16,
  gap: 20,
  margin: 12,
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

/** Where a net's wires branch: a dot, as a schematic draws a joint. */
export type DiagramJunction = { key: string; net: string; x: number; y: number };

export type Diagram = {
  width: number;
  height: number;
  parts: DiagramPart[];
  wires: DiagramWire[];
  junctions: DiagramJunction[];
  labels: DiagramLabel[];
};

const byNumber = new Intl.Collator("en", { numeric: true });

/**
 * Lays a revision's nets out as a drawing: the part with the most wired pins is the hub, on the
 * left, and every other part stacks on the right, facing it, in the order of the hub pins it is
 * wired to. A part shows only its wired pins, in pin order.
 *
 * The wires are routed the way a breadboard drawing has them: straight runs and right angles
 * only, and no two wires on top of each other. Each net owns one vertical run in the channel
 * between the columns, and reaches each of its pins level from it; the two columns' pins sit
 * half a row apart, so a level run from the left never lies on one from the right. Wires still
 * cross, as they must, but the runs are ordered to cross as little as a few swaps can make
 * them. Nothing here measures the page: the same nets always give the same drawing.
 */
export function layoutDiagram(nets: readonly Net[]): Diagram {
  const pinsOf = new Map<string, Map<string, NetPin>>();
  for (const net of nets)
    for (const pin of net.pins) {
      const pins = pinsOf.get(pin.designator) ?? new Map<string, NetPin>();
      if (!pins.has(pin.ref)) pins.set(pin.ref, pin);
      pinsOf.set(pin.designator, pins);
    }
  if (pinsOf.size === 0)
    return { width: 0, height: 0, parts: [], wires: [], junctions: [], labels: [] };

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
  const leftX = DIAGRAM.margin;
  const place = (designator: string, side: "left" | "right", y: number): DiagramPart => {
    const pins = sorted(designator);
    return {
      designator,
      name: pins.find((pin) => pin.part_name)?.part_name ?? null,
      side,
      // The right column's place depends on the channel's width, known once the nets are routed.
      x: leftX,
      y,
      width: DIAGRAM.partWidth,
      height: heightOf(designator),
      pins: pins.map((pin, row) => ({
        ref: pin.ref,
        pin: pin.pin,
        label: pin.label ?? null,
        known: pin.resolution === "resolved" || pin.resolution === "unchecked",
        x: leftX + (side === "left" ? DIAGRAM.partWidth : 0),
        y: y + DIAGRAM.header + row * DIAGRAM.row + DIAGRAM.row / 2,
      })),
    };
  };

  const stack = others.reduce((sum, other) => sum + heightOf(other) + DIAGRAM.gap, -DIAGRAM.gap);
  const inner = Math.max(heightOf(hub), stack);
  const hubY = DIAGRAM.margin + Math.round((inner - heightOf(hub)) / 2);
  const parts = [place(hub, "left", hubY)];
  let y = DIAGRAM.margin + Math.round((inner - Math.max(stack, 0)) / 2);
  for (const other of others) {
    // Half a row off the hub's rows, so no pin here is level with one of the hub's.
    y += mod(DIAGRAM.row / 2 - (y - hubY), DIAGRAM.row);
    parts.push(place(other, "right", y));
    y += heightOf(other) + DIAGRAM.gap;
  }

  const at = new Map(
    parts.flatMap((part) => part.pins.map((pin) => [pin.ref, { ...pin, side: part.side }])),
  );
  const routes: Route[] = [];
  const labels: (DiagramLabel & { side: "left" | "right" })[] = [];
  for (const net of nets) {
    const refs = [...new Set(net.pins.map((pin) => pin.ref))];
    const start = refs.find((ref) => hubRow.has(ref)) ?? refs[0];
    const from = start === undefined ? undefined : at.get(start);
    if (!from) continue;
    // The net's name reads beside the pin its wires leave from, on the channel's side.
    labels.push({
      key: net.id,
      net: net.name,
      x: from.side === "left" ? 8 : -8,
      y: from.y - 5,
      anchor: from.side === "left" ? "start" : "end",
      side: from.side,
    });
    const to = refs.filter((ref) => ref !== start).flatMap((ref) => at.get(ref) ?? []);
    if (to.length > 0) routes.push({ net, from, to });
  }

  // The names sit between a column and the nearest run, so the channel leaves them room.
  const room = (side: "left" | "right") =>
    Math.max(
      DIAGRAM.lead,
      ...labels
        .filter((label) => label.side === side)
        .map((label) => Math.min(label.net.length, DIAGRAM.labelLength) * 6.5 + 16),
    );
  const runs = Math.max(routes.length - 1, 0) * DIAGRAM.track;
  const channel = Math.max(DIAGRAM.channel, room("left") + runs + room("right"));
  const firstRun =
    leftX + DIAGRAM.partWidth + room("left") + (channel - room("left") - room("right") - runs) / 2;
  const rightX = leftX + DIAGRAM.partWidth + channel;
  for (const part of parts)
    if (part.side === "right") {
      part.x = rightX;
      for (const pin of part.pins) pin.x = rightX;
    }
  const edge = ({ side }: { side: "left" | "right" }) =>
    side === "left" ? leftX + DIAGRAM.partWidth : rightX;

  const wires: DiagramWire[] = [];
  const junctions: DiagramJunction[] = [];
  uncrossed(routes).forEach(({ net, from, to }, index) => {
    const run = firstRun + index * DIAGRAM.track;
    const ys = [from, ...to].map((pin) => pin.y);
    // A net's wires share nothing: the first one brings the starting pin to the run, and each
    // takes the run on from the pin before it, up or down, then turns level to its own pin.
    const reached = (pin: Placed) => {
      const nearer = ys.filter((each) =>
        pin.y < from.y ? each > pin.y && each <= from.y : each < pin.y && each >= from.y,
      );
      return pin.y < from.y ? Math.min(...nearer) : Math.max(...nearer);
    };
    to.forEach((pin, nth) => {
      const lead = nth === 0 ? `M ${edge(from)} ${from.y} H ${run} ` : "";
      wires.push({
        key: `${net.id}:${pin.ref}`,
        net: net.name,
        color: net.color ?? null,
        from: from.ref,
        to: pin.ref,
        path: `${lead}M ${run} ${reached(pin)} V ${pin.y} H ${edge(pin)}`,
      });
    });
    for (const each of ys)
      if (each > Math.min(...ys) && each < Math.max(...ys))
        junctions.push({ key: `${net.id}:${each}`, net: net.name, x: run, y: each });
  });

  const single = others.length === 0;
  return {
    width: (single ? rightX : rightX + DIAGRAM.partWidth) + DIAGRAM.margin,
    height: Math.max(...parts.map((part) => part.y + part.height)) + DIAGRAM.margin,
    parts,
    wires,
    junctions,
    labels: labels.map(({ side, ...label }) => ({
      ...label,
      x: edge({ side }) + label.x,
    })),
  };
}

type Placed = DiagramPin & { side: "left" | "right" };
type Route = { net: Net; from: Placed; to: Placed[] };

function mod(value: number, by: number): number {
  return ((value % by) + by) % by;
}

/** How often two nets' wires cross when A's run is left of B's. */
function crossings(a: Route, b: Route): number {
  const within = (route: Route, y: number) => {
    const ys = [route.from, ...route.to].map((pin) => pin.y);
    return y > Math.min(...ys) && y < Math.max(...ys);
  };
  const pins = (route: Route, side: "left" | "right") =>
    [route.from, ...route.to].filter((pin) => pin.side === side);
  // B's level runs to the left column pass A's run, and A's to the right column pass B's.
  return (
    pins(b, "left").filter((pin) => within(a, pin.y)).length +
    pins(a, "right").filter((pin) => within(b, pin.y)).length
  );
}

/**
 * The nets in the order of their runs, left to right: neighbours are swapped for as long as a
 * swap takes crossings away. A pass can't undo another's gain without finding fewer crossings
 * itself, and the passes are counted, so this always ends.
 */
function uncrossed(routes: readonly Route[]): Route[] {
  const order = [...routes].sort((a, b) => b.from.y - a.from.y);
  for (let pass = 0; pass < order.length; pass += 1) {
    let swapped = false;
    for (let at = 0; at + 1 < order.length; at += 1) {
      const [left, right] = [order[at] as Route, order[at + 1] as Route];
      if (crossings(right, left) < crossings(left, right)) {
        order[at] = right;
        order[at + 1] = left;
        swapped = true;
      }
    }
    if (!swapped) break;
  }
  return order;
}
