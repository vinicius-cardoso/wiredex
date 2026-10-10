import { describe, expect, it } from "vitest";
import { parseWiring } from "./paste";

const net = (row: Partial<ReturnType<typeof parseWiring>["rows"][number]>) => ({
  name: null,
  color: null,
  notes: null,
  problem: null,
  ...row,
});

describe("pasted wiring", () => {
  it("reads one net per line, with its name and colour", () => {
    const { between, rows } = parseWiring("SDA; U1.25, U2.3; blue\nGND\tU1.14 U2.1\tblack");

    expect(between).toBeNull();
    expect(rows).toEqual([
      net({ line: 1, name: "SDA", pins: "U1.25, U2.3", color: "blue" }),
      net({ line: 2, name: "GND", pins: "U1.14, U2.1", color: "black" }),
    ]);
  });

  it("takes the cells in any order, and keeps what is left as notes", () => {
    const { rows } = parseWiring("rosa; U1.4, R1.1; LED; through the resistor; 330R");

    expect(rows).toEqual([
      net({
        line: 1,
        name: "LED",
        color: "pink",
        pins: "U1.4, R1.1",
        notes: "through the resistor; 330R",
      }),
    ]);
  });

  it("reads a line of nothing but pins, and one split by commas alone", () => {
    const { rows } = parseWiring("U1.25, U2.SDA\n3.3V, U1.1, U2.2, vermelho");

    expect(rows).toEqual([
      net({ line: 1, pins: "U1.25, U2.SDA" }),
      net({ line: 2, name: "3.3V", pins: "U1.1, U2.2", color: "red" }),
    ]);
  });

  it("skips a heading and blank lines, keeping each line's own number", () => {
    const { rows } = parseWiring("Net; Pins; Color\n\nSCL; U1.22, U2.4; yellow\n");

    expect(rows).toEqual([net({ line: 3, name: "SCL", pins: "U1.22, U2.4", color: "yellow" })]);
  });

  it("marks a line with no pin on it", () => {
    const { rows } = parseWiring("SDA; U1.25, U2.3\nSCL; yellow");

    expect(rows[1]).toEqual(
      net({ line: 2, name: "SCL", color: "yellow", pins: "", problem: "noPins" }),
    );
  });

  it("reads the connections between two parts from a line of two designators", () => {
    const { between, rows } = parseWiring("u1; U2\n25; SDA\n22\tSCL\tclock\tamarelo\n14, GND");

    expect(between).toEqual(["U1", "U2"]);
    expect(rows).toEqual([
      net({ line: 2, pins: "U1.25, U2.SDA" }),
      net({ line: 3, pins: "U1.22, U2.SCL", name: "clock", color: "yellow" }),
      net({ line: 4, pins: "U1.14, U2.GND" }),
    ]);
  });

  it("lets the two designators head columns for a name and a colour", () => {
    const { between, rows } = parseWiring("U1\tJ1\tNet\tColor\n5\t1\tVBUS\tred");

    expect(between).toEqual(["U1", "J1"]);
    expect(rows).toEqual([net({ line: 2, pins: "U1.5, J1.1", name: "VBUS", color: "red" })]);
  });

  it("marks a line between two parts that names only one pin", () => {
    const { rows } = parseWiring("U1; U2\n25");

    expect(rows).toEqual([net({ line: 2, pins: "", problem: "needsTwo" })]);
  });

  it("reads nothing from nothing", () => {
    expect(parseWiring("  \n")).toEqual({ between: null, rows: [] });
  });
});
