import { describe, expect, it } from "vitest";
import { aNet, aNetPin } from "../../../test/server";
import { DIAGRAM, layoutDiagram } from "./diagram";

const pin = (ref: string, label: string | null = null) => {
  const [designator = "", number = ""] = ref.split(".");
  return aNetPin({ ref, designator, pin: number, label, part_name: `Part ${designator}` });
};
const net = (id: string, name: string, refs: string[]) =>
  aNet({ id, name, pins: refs.map((ref) => pin(ref)) });

describe("layoutDiagram", () => {
  it("draws nothing for no nets", () => {
    expect(layoutDiagram([])).toEqual({
      width: 0,
      height: 0,
      parts: [],
      wires: [],
      junctions: [],
      labels: [],
    });
  });

  it("puts the part with the most wired pins on the left, its pins in pin order", () => {
    const diagram = layoutDiagram([
      net("n1", "SCL", ["U1.22", "U2.4"]),
      net("n2", "SDA", ["U2.3", "U1.21"]),
      net("n3", "3V3", ["U1.3", "U2.1", "R1.1"]),
    ]);
    const [hub, ...others] = diagram.parts;
    expect(hub).toMatchObject({ designator: "U1", side: "left", name: "Part U1" });
    expect(hub?.pins.map((each) => each.pin)).toEqual(["3", "21", "22"]);
    expect(others.map((part) => [part.designator, part.side])).toEqual([
      ["R1", "right"],
      ["U2", "right"],
    ]);
    // A hub pin's wires leave its right edge; the other parts take theirs on the left edge.
    expect(hub?.pins.every((each) => each.x === (hub?.x ?? 0) + DIAGRAM.partWidth)).toBe(true);
    for (const part of others) expect(part.pins.every((each) => each.x === part.x)).toBe(true);
    // Every part is inside the drawing, and the right column's parts don't overlap.
    for (const part of diagram.parts) {
      expect(part.x + part.width).toBeLessThanOrEqual(diagram.width);
      expect(part.y + part.height).toBeLessThanOrEqual(diagram.height);
    }
    const [first, second] = others;
    expect((first?.y ?? 0) + (first?.height ?? 0)).toBeLessThan(second?.y ?? 0);
  });

  it("draws a net from the hub's pin to each of its other pins, named beside that pin", () => {
    const diagram = layoutDiagram([
      net("n1", "3V3", ["R1.1", "U1.3", "U2.1"]),
      net("n2", "SDA", ["U1.21", "U2.3"]),
      net("n3", "SCL", ["U1.22", "U2.4"]),
    ]);
    const power = diagram.wires.filter((wire) => wire.net === "3V3");
    expect(power.map((wire) => [wire.from, wire.to])).toEqual([
      ["U1.3", "R1.1"],
      ["U1.3", "U2.1"],
    ]);
    const hubPin = diagram.parts[0]?.pins.find((each) => each.ref === "U1.3");
    expect(power[0]?.path.startsWith(`M ${hubPin?.x} ${hubPin?.y} H`)).toBe(true);
    expect(diagram.labels.find((label) => label.net === "3V3")).toMatchObject({
      x: (hubPin?.x ?? 0) + 8,
      anchor: "start",
    });
  });

  it("runs a wire between two pins of one column through the channel", () => {
    const diagram = layoutDiagram([
      net("n1", "LOOP", ["U1.1", "U1.9"]),
      net("n2", "A", ["U1.2", "R1.1"]),
      net("n3", "B", ["U1.3", "R2.1"]),
      net("n4", "PULL", ["R1.2", "R2.2"]),
    ]);
    const hubEdge = diagram.parts[0]?.pins[0]?.x ?? 0;
    const rightEdge = diagram.parts[1]?.x ?? 0;
    for (const name of ["LOOP", "PULL"]) {
      const wire = diagram.wires.find((each) => each.net === name);
      const run = runsOf(wire?.path ?? "").find((each) => each.x1 === each.x2);
      expect(run?.x1).toBeGreaterThan(hubEdge);
      expect(run?.x1).toBeLessThan(rightEdge);
    }
    // Neither part of PULL is the hub, so it starts at its first pin, named on its side.
    const pull = diagram.wires.find((wire) => wire.net === "PULL");
    expect([pull?.from, pull?.to]).toEqual(["R1.2", "R2.2"]);
    expect(diagram.labels.find((label) => label.net === "PULL")?.anchor).toBe("end");
  });

  it("draws straight runs and right angles only, none on top of another", () => {
    const diagram = layoutDiagram([
      net("n1", "3V3", ["U1.3", "U2.1", "R1.1", "U3.1"]),
      net("n2", "GND", ["U1.4", "U2.2", "U3.2", "R2.2"]),
      net("n3", "SDA", ["U1.21", "U2.3", "U3.3"]),
      net("n4", "SCL", ["U1.22", "U2.4", "U3.4"]),
      net("n5", "LOOP", ["U1.1", "U1.9"]),
      net("n6", "PULL", ["R1.2", "R2.1", "U2.5"]),
    ]);
    const runs = diagram.wires.flatMap((wire) => runsOf(wire.path));
    expect(diagram.wires.every((wire) => /^[MHV\d. ]+$/.test(wire.path))).toBe(true);
    for (const [at, a] of runs.entries())
      for (const b of runs.slice(at + 1)) expect(overlap(a, b), JSON.stringify([a, b])).toBe(false);
  });

  it("gives each net its own run, and a joint where a net branches", () => {
    const diagram = layoutDiagram([
      net("n1", "3V3", ["U1.3", "U2.1", "R1.1"]),
      net("n2", "SDA", ["U1.21", "U2.3"]),
    ]);
    const upright = (name: string) =>
      new Set(
        diagram.wires
          .filter((wire) => wire.net === name)
          .flatMap((wire) => runsOf(wire.path))
          .filter((run) => run.x1 === run.x2)
          .map((run) => run.x1),
      );
    expect(upright("3V3").size).toBe(1);
    expect(upright("SDA").size).toBe(1);
    expect([...upright("3V3")][0]).not.toBe([...upright("SDA")][0]);
    // Three pins meet at one point of the run; two pins are one wire with no joint.
    expect(diagram.junctions.map((junction) => junction.net)).toEqual(["3V3"]);
    expect(diagram.junctions[0]?.x).toBe([...upright("3V3")][0]);
  });

  it("orders the runs so two nets that needn't cross don't", () => {
    // Both nets go down and to the right: the upper one takes the run further right.
    const diagram = layoutDiagram([
      net("n1", "A", ["U1.1", "R1.1"]),
      net("n2", "B", ["U1.2", "R1.2"]),
      net("n3", "C", ["U1.3", "R2.1"]),
      net("n4", "D", ["U1.4", "R2.2"]),
    ]);
    const runs = diagram.wires.flatMap((wire) => runsOf(wire.path));
    const crossing = runs.flatMap((a, at) =>
      runs.slice(at + 1).filter((b) => {
        const [level, upright] = a.y1 === a.y2 ? [a, b] : [b, a];
        if (level.y1 !== level.y2 || upright.x1 !== upright.x2) return false;
        const between = (value: number, one: number, other: number) =>
          value > Math.min(one, other) && value < Math.max(one, other);
        return between(upright.x1, level.x1, level.x2) && between(level.y1, upright.y1, upright.y2);
      }),
    );
    expect(crossing).toEqual([]);
  });

  it("marks a pin the pinout doesn't have, and draws a repeated pin once", () => {
    const stray = aNetPin({ ref: "U1.99", pin: "99", resolution: "unknown_pin", label: null });
    const diagram = layoutDiagram([
      aNet({ id: "n1", name: "X", pins: [aNetPin(), stray] }),
      aNet({ id: "n2", name: "Y", pins: [aNetPin(), pin("R1.1")] }),
    ]);
    expect(diagram.parts[0]?.pins.map((each) => [each.ref, each.known])).toEqual([
      ["U1.25", true],
      ["U1.99", false],
    ]);
  });
});

type Run = { x1: number; y1: number; x2: number; y2: number };

/** A path of M, H and V commands as its straight runs. */
function runsOf(path: string): Run[] {
  const runs: Run[] = [];
  let [x, y] = [0, 0];
  for (const [, command, first, second] of path.matchAll(/([MHV]) (-?[\d.]+)(?: (-?[\d.]+))?/g)) {
    const [fromX, fromY] = [x, y];
    if (command === "M") [x, y] = [Number(first), Number(second)];
    else if (command === "H") x = Number(first);
    else y = Number(first);
    if (command !== "M") runs.push({ x1: fromX, y1: fromY, x2: x, y2: y });
  }
  return runs;
}

/** Whether two runs lie on the same line and share more than a point. */
function overlap(a: Run, b: Run): boolean {
  const shared = (a1: number, a2: number, b1: number, b2: number) =>
    Math.min(Math.max(a1, a2), Math.max(b1, b2)) - Math.max(Math.min(a1, a2), Math.min(b1, b2)) > 0;
  const level = (run: Run) => run.y1 === run.y2;
  if (level(a) && level(b)) return a.y1 === b.y1 && shared(a.x1, a.x2, b.x1, b.x2);
  if (!level(a) && !level(b)) return a.x1 === b.x1 && shared(a.y1, a.y2, b.y1, b.y2);
  return false;
}
