import { describe, expect, it } from "vitest";
import { type ParsedRow, parsePinTable } from "./paste";
import { PIN_TYPES } from "./pinTypes";

/** A row with the cells a test cares about; the rest empty, as a short paste leaves them. */
function row(cells: Partial<ParsedRow> = {}): ParsedRow {
  return {
    number: "",
    label: "",
    type: "",
    functions: [],
    voltage: "",
    warnings: [],
    ...cells,
  };
}

/** The first row, for the tests that paste a single line. */
function firstRow(text: string): ParsedRow | undefined {
  return parsePinTable(text)[0];
}

describe("parsePinTable", () => {
  it("reads a spreadsheet copy, tabs and all", () => {
    const pasted = ["1\tGND\tGND\t\t", "3\tSDI\tI/O\tSDA/MOSI\t3V3"].join("\n");

    expect(parsePinTable(pasted)).toEqual([
      row({ number: "1", label: "GND", type: "ground" }),
      row({ number: "3", label: "SDI", type: "io", functions: ["SDA", "MOSI"], voltage: "3V3" }),
    ]);
  });

  it("reads a semicolon table", () => {
    expect(parsePinTable("2;VOUT;power;;3V3")).toEqual([
      row({ number: "2", label: "VOUT", type: "power", voltage: "3V3" }),
    ]);
  });

  it("reads a comma table", () => {
    expect(parsePinTable("4,SCK,io,SCL I2C_CLK,3V3")).toEqual([
      row({ number: "4", label: "SCK", type: "io", functions: ["SCL", "I2C_CLK"], voltage: "3V3" }),
    ]);
  });

  it("splits functions on a comma when the comma isn't the separator", () => {
    expect(firstRow("3\tSDI\tio\tSDA, MOSI")?.functions).toEqual(["SDA", "MOSI"]);
    expect(firstRow("3\tSDI\tio\tSDA|MOSI;SDI")?.functions).toEqual(["SDA", "MOSI", "SDI"]);
  });

  it.each([
    { language: "an English", header: "Pin;Name;Type;Functions;Voltage" },
    { language: "a Portuguese", header: "Pino;Nome;Tipo;Funções;Tensão" },
    { language: "a half-filled", header: "Pin #;Label;;;" },
  ])("skips $language header", ({ header }) => {
    expect(parsePinTable(`${header}\n1;GND;gnd`)).toEqual([
      row({ number: "1", label: "GND", type: "ground" }),
    ]);
  });

  it("keeps a first line that starts at a pin number, whatever words follow", () => {
    // `TYPE_SEL` is a label a header check must not mistake for the type column.
    expect(parsePinTable("1;TYPE_SEL;io")).toEqual([
      row({ number: "1", label: "TYPE_SEL", type: "io" }),
    ]);
  });

  it("fills a short row instead of dropping it", () => {
    expect(parsePinTable("7;CSB")).toEqual([row({ number: "7", label: "CSB" })]);
  });

  it.each([
    ["I/O", "io"],
    ["N/C", "nc"],
    ["PWR", "power"],
    ["GPIO", "io"],
    ["IN", "input"],
    ["OUT", "output"],
    ["AI", "analog"],
    ["not connected", "nc"],
  ])("maps a pasted %s to %s", (spelled, expected) => {
    expect(firstRow(`1;SDA;${spelled}`)).toEqual(
      row({ number: "1", label: "SDA", type: expected }),
    );
  });

  it.each(PIN_TYPES)("takes %s back unchanged, as the API spells it", (type) => {
    expect(firstRow(`1;SDA;${type}`)?.type).toBe(type);
  });

  it("keeps a type it doesn't know and marks the row", () => {
    expect(parsePinTable("1;XTAL;clock")).toEqual([
      row({ number: "1", label: "XTAL", type: "clock", warnings: ["unknownType"] }),
    ]);
  });

  it.each([
    ["VCC", "power"],
    ["3V3", "power"],
    ["5V", "power"],
    ["VIN", "power"],
    ["GND", "ground"],
    ["VSS", "ground"],
  ])("guesses a %s row with no type as %s, and says it guessed", (label, expected) => {
    expect(firstRow(`1;${label}`)).toEqual(
      row({ number: "1", label, type: expected, warnings: ["typeGuessed"] }),
    );
  });

  it.each(["SDA", "VREF", "GNDSENSE"])("guesses nothing from %s, which is no rail", (label) => {
    expect(firstRow(`1;${label}`)).toEqual(row({ number: "1", label }));
  });
});

/**
 * Property 6: pasting never loses a row. One row per line that holds anything, minus a
 * detected header, in the order pasted, whatever the separator and however short a line is.
 *
 * **Validates: Requirements 6.2, 6.3, 6.4**
 */
describe("property 6: pasting never loses a row", () => {
  it.each([
    {
      paste: "tab-separated",
      text: "1\tGND\tgnd\n2\tVOUT\tpwr\n3\tVIN\tpwr",
      numbers: ["1", "2", "3"],
    },
    { paste: "semicolon-separated", text: "1;GND;gnd\n2;VOUT;pwr", numbers: ["1", "2"] },
    { paste: "comma-separated", text: "1,GND,gnd\n2,VOUT,pwr", numbers: ["1", "2"] },
    { paste: "headed", text: "Pin\tName\tType\n1\tGND\tgnd\n2\tVOUT\tpwr", numbers: ["1", "2"] },
    { paste: "ragged", text: "1\tGND\tgnd\n2\tVOUT\n3", numbers: ["1", "2", "3"] },
    {
      paste: "blank-lined, CRLF",
      text: "\r\n1;GND;gnd\r\n\r\n2;VOUT;pwr\r\n",
      numbers: ["1", "2"],
    },
    { paste: "wider than five columns", text: "1;GND;gnd;;0;a note", numbers: ["1"] },
    { paste: "single-column", text: "1\n2\n3", numbers: ["1", "2", "3"] },
    { paste: "header-only", text: "Pin;Name;Type", numbers: [] },
    { paste: "empty", text: "", numbers: [] },
    { paste: "blank", text: "  \n\n\t\n", numbers: [] },
    { paste: "nothing but separators", text: ";;;;", numbers: [""] },
  ])("keeps every line of a $paste paste, in order", ({ text, numbers }) => {
    expect(parsePinTable(text).map((parsed) => parsed.number)).toEqual(numbers);
  });
});
