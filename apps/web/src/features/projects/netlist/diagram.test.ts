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
    expect(layoutDiagram([])).toEqual({ width: 0, height: 0, parts: [], wires: [], labels: [] });
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
    expect(power[0]?.path.startsWith(`M ${hubPin?.x} ${hubPin?.y} C`)).toBe(true);
    expect(diagram.labels.find((label) => label.net === "3V3")).toMatchObject({
      x: (hubPin?.x ?? 0) + 8,
      anchor: "start",
    });
  });

  it("bows a wire between two pins of one column out of it, inside the drawing", () => {
    const diagram = layoutDiagram([
      net("n1", "LOOP", ["U1.1", "U1.9"]),
      net("n2", "A", ["U1.2", "R1.1"]),
      net("n3", "B", ["U1.3", "R2.1"]),
      net("n4", "PULL", ["R1.2", "R2.2"]),
    ]);
    const xs = (path: string) =>
      [...path.matchAll(/(-?[\d.]+) (-?[\d.]+)/g)].map((match) => Number(match[1]));
    const hubEdge = diagram.parts[0]?.pins[0]?.x ?? 0;
    const loop = diagram.wires.find((wire) => wire.net === "LOOP");
    expect(Math.max(...xs(loop?.path ?? ""))).toBeGreaterThan(hubEdge);
    // Neither part of PULL is the hub, so it starts at its first pin and bows into the channel.
    const pull = diagram.wires.find((wire) => wire.net === "PULL");
    expect([pull?.from, pull?.to]).toEqual(["R1.2", "R2.2"]);
    const rightEdge = diagram.parts[1]?.x ?? 0;
    expect(Math.min(...xs(pull?.path ?? ""))).toBeLessThan(rightEdge);
    expect(Math.min(...xs(pull?.path ?? ""))).toBeGreaterThan(hubEdge);
    expect(diagram.labels.find((label) => label.net === "PULL")?.anchor).toBe("end");
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
