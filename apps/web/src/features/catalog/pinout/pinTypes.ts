/**
 * The eight pin types, and the words a pasted table writes them with.
 *
 * The API accepts exactly the eight names and refuses everything else, on purpose: a
 * datasheet's `PWR`, `I/O` or `N/C` is mapped here, in the browser, where the guess lands on
 * a row the owner reviews before anything is saved (requirement 6.5). Nothing in this module
 * decides whether a pin is valid — that stays the domain's, and its refusal names the row
 * and the cell to fix.
 */

import type { PinType } from "@wiredex/api-client";

/** The eight types, in the order the editor's select offers them (requirement 2.6). */
export const PIN_TYPES = [
  "power",
  "ground",
  "io",
  "input",
  "output",
  "analog",
  "nc",
  "other",
] as const satisfies readonly PinType[];

// The spellings that aren't one of the eight names. Single letters are in because a compact
// pinout table prints a column of `P`, `G`, `I`, `O`; `not connected` because a datasheet
// writes it out. Requirement 6.5 names `PWR`, `VCC`, `GND`, `I/O`, `GPIO`, `IN`, `OUT`, `AI`
// and `N/C`; the rest are their immediate neighbours (`vdd` beside `vcc`).
const TYPE_BY_SPELLING = new Map<string, PinType>([
  ["pwr", "power"],
  ["vcc", "power"],
  ["vdd", "power"],
  ["supply", "power"],
  ["p", "power"],
  ["gnd", "ground"],
  ["vss", "ground"],
  ["g", "ground"],
  ["i/o", "io"],
  ["gpio", "io"],
  ["bidir", "io"],
  ["inout", "io"],
  ["in", "input"],
  ["i", "input"],
  ["out", "output"],
  ["o", "output"],
  ["analogue", "analog"],
  ["ai", "analog"],
  ["a", "analog"],
  ["adc", "analog"],
  ["nc", "nc"],
  ["n/c", "nc"],
  ["not connected", "nc"],
]);

// The labels a rail is printed with, matched whole. Whole and not as a substring because
// `VREF` and `GNDSENSE` are not what requirement 6.6 asks to guess: it lists the rails, and
// a guess that reaches further is a guess the owner has to undo.
const TYPE_BY_LABEL = new Map<string, PinType>([
  ["vcc", "power"],
  ["vdd", "power"],
  ["vin", "power"],
  ["vbat", "power"],
  ["3v3", "power"],
  ["5v", "power"],
  ["gnd", "ground"],
  ["vss", "ground"],
  ["agnd", "ground"],
]);

/**
 * Whether a cell already holds one of the eight names. What a paste kept as it was isn't one
 * (requirement 6.5), so the editor shows that text as it stands instead of a translated name.
 */
export function isPinType(value: string): value is PinType {
  return PIN_TYPES.some((type) => type === value);
}

/**
 * The type a pasted cell spells, or null when nothing here recognizes it (requirement 6.5).
 * The eight names are read first, so `power` and `other` need no spelling of their own.
 */
export function pinTypeOf(cell: string): PinType | null {
  const spelling = fold(cell);
  return PIN_TYPES.find((type) => type === spelling) ?? TYPE_BY_SPELLING.get(spelling) ?? null;
}

/**
 * The type a power or ground label gives away, for a row that pasted no type at all
 * (requirement 6.6), or null when the label says nothing about it.
 */
export function pinTypeFromLabel(label: string): PinType | null {
  return TYPE_BY_LABEL.get(fold(label)) ?? null;
}

/** Lower-cased with its whitespace collapsed, so `Not  Connected` reads as one spelling. */
function fold(text: string): string {
  return text.trim().toLowerCase().split(/\s+/).join(" ");
}
