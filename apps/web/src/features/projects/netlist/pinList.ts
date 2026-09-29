import type { Netlist } from "@wiredex/api-client";

/** The item of a pin list the caret is in: its text and where it sits in the field. */
export type Token = { start: number; end: number; text: string };

const SEPARATOR = /[\s,]/;

/** The item around `caret`, items being split by commas and whitespace as the API reads them. */
export function tokenAt(text: string, caret: number): Token {
  let start = caret;
  while (start > 0 && !SEPARATOR.test(text.charAt(start - 1))) start -= 1;
  let end = caret;
  while (end < text.length && !SEPARATOR.test(text.charAt(end))) end += 1;
  return { start, end, text: text.slice(start, end) };
}

/** The field with the item replaced, and where the caret goes after it. */
export function replaceToken(text: string, token: Token, value: string): [string, number] {
  return [text.slice(0, token.start) + value + text.slice(token.end), token.start + value.length];
}

/**
 * One suggestion: what picking it writes into the item, and what the list shows. A designator
 * writes `U1.` and stays open for its pins; a pin writes `U1.25`, its number (decision 14).
 */
export type Suggestion = { value: string; primary: string; secondary: string; final: boolean };

const MOST = 20;

/**
 * What the item being typed could become (requirement 10.4): before a dot, the BOM's
 * designators starting with it, each with its part's name; after one, the pins of that
 * designator's part whose number, label or function starts with what follows, each written by
 * number. A part with no pinout offers nothing to pick, since any pin number goes.
 */
export function suggestionsFor(item: string, netlist: Netlist | undefined): Suggestion[] {
  if (!netlist) return [];
  const dot = item.indexOf(".");
  if (dot === -1) {
    const typed = item.toUpperCase();
    return netlist.designators
      .filter((entry) => entry.designator.startsWith(typed))
      .slice(0, MOST)
      .map((entry) => ({
        value: `${entry.designator}.`,
        primary: entry.designator,
        secondary: entry.part_name ?? "",
        final: false,
      }));
  }
  const designator = item.slice(0, dot).toUpperCase();
  const typed = item.slice(dot + 1).toLowerCase();
  const entry = netlist.designators.find((candidate) => candidate.designator === designator);
  const part = netlist.parts.find((candidate) => candidate.part_id === entry?.part_id);
  if (!part) return [];
  return part.pins
    .filter((pin) =>
      [pin.number, pin.label, ...pin.functions].some((name) =>
        name.toLowerCase().startsWith(typed),
      ),
    )
    .slice(0, MOST)
    .map((pin) => ({
      value: `${designator}.${pin.number}`,
      primary: pin.number,
      secondary: [pin.label, ...pin.functions].join(" · "),
      final: true,
    }));
}
