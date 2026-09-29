import { describe, expect, it } from "vitest";
import { aNetlist } from "../../../test/server";
import { replaceToken, suggestionsFor, tokenAt } from "./pinList";

const netlist = aNetlist({
  nets: [],
  designators: [
    { designator: "R1", part_id: "r", part_name: "Resistor 4k7" },
    { designator: "U1", part_id: "esp", part_name: "ESP32-DevKitC" },
    { designator: "U2", part_id: "bme", part_name: "BME280" },
  ],
  parts: [
    { part_id: "r", name: "Resistor 4k7", has_pinout: false, pins: [] },
    {
      part_id: "esp",
      name: "ESP32-DevKitC",
      has_pinout: true,
      pins: [
        { number: "22", label: "GPIO22", type: "io", functions: ["SCL"], voltage: "3.3" },
        { number: "25", label: "GPIO21", type: "io", functions: ["SDA"], voltage: "3.3" },
      ],
    },
  ],
});

describe("tokenAt", () => {
  it("finds the item under the caret, split by commas and spaces", () => {
    expect(tokenAt("U1.25, U2.S", 11)).toEqual({ start: 7, end: 11, text: "U2.S" });
    expect(tokenAt("U1.25, U2", 3)).toEqual({ start: 0, end: 5, text: "U1.25" });
  });

  it("replaces only that item", () => {
    expect(replaceToken("R1.2, U", tokenAt("R1.2, U", 7), "U1.")).toEqual(["R1.2, U1.", 9]);
  });
});

describe("suggestionsFor", () => {
  it("offers designators before a dot, with their parts", () => {
    expect(suggestionsFor("u", netlist).map((s) => [s.value, s.secondary])).toEqual([
      ["U1.", "ESP32-DevKitC"],
      ["U2.", "BME280"],
    ]);
  });

  it("offers a part's pins by number, label or function, written by number", () => {
    expect(suggestionsFor("U1.sd", netlist).map((s) => s.value)).toEqual(["U1.25"]);
    expect(suggestionsFor("U1.gpio2", netlist).map((s) => s.value)).toEqual(["U1.22", "U1.25"]);
    expect(suggestionsFor("U1.2", netlist).map((s) => s.value)).toEqual(["U1.22", "U1.25"]);
  });

  it("offers nothing for a part with no pinout or no netlist", () => {
    expect(suggestionsFor("R1.", netlist)).toEqual([]);
    expect(suggestionsFor("U", undefined)).toEqual([]);
  });
});
