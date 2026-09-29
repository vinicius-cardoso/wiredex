import type { BomRefusalCode } from "@wiredex/api-client";

/**
 * The server's designator rules (09's decisions 5 and 6), mirrored for the live preview.
 *
 * The server's answer is what gets stored, so a disagreement here costs a 422 on the line,
 * never a wrong line. The rules are kept exact anyway, so the preview says what the server
 * will: `r1-4, R7` reads as `R1–R4, R7`, and `R0` is refused as the server refuses it.
 */

export const MAX_DESIGNATOR_LETTERS = 8;
export const MAX_DESIGNATOR_NUMBER = 9_999;
export const MAX_DESIGNATORS = 256;

export type Designator = { letters: string; number: number };

/** Why a list can't be read: the server's codes for a designator list, and what they name. */
export type DesignatorProblem = {
  code: Extract<
    BomRefusalCode,
    "invalid_designator" | "invalid_range" | "repeated_designator" | "too_many_designators"
  >;
  item: string | null;
};

export type DesignatorReading =
  | { designators: Designator[]; text: string; count: number; problem: null }
  | { designators: null; text: null; count: null; problem: DesignatorProblem };

// Explicit ASCII classes, as the server's are: NFKC folds fullwidth letters and digits into
// these, and other scripts' digits stay refused.
const DESIGNATOR = /^([A-Za-z]+)([0-9]+)$/;
const DIGITS = /^[0-9]+$/;
const DASHES = /[-–—]/;
const AROUND_A_DASH = /\s*([-–—])\s*/g;
const SEPARATORS = /[,\s]+/;
// Three in a row is the shortest run written as a range: `R1, R2` reads plainer than `R1–R2`.
const SHORTEST_RANGE = 3;

class Refused extends Error {
  constructor(readonly problem: DesignatorProblem) {
    super(problem.code);
  }
}

/** A list as typed: its designators in canonical order, their canonical text and count. */
export function readDesignators(text: string): DesignatorReading {
  try {
    const closedUp = text.normalize("NFKC").replace(AROUND_A_DASH, "$1");
    const reading = new Reading();
    for (const item of closedUp.split(SEPARATORS)) {
      if (item) reading.read(item);
    }
    const designators = [...reading.designators].sort(compare);
    return {
      designators,
      text: designatorText(designators),
      count: designators.length,
      problem: null,
    };
  } catch (error) {
    if (error instanceof Refused) {
      return { designators: null, text: null, count: null, problem: error.problem };
    }
    throw error;
  }
}

/** The canonical text of designators already in canonical order: `C1, R1–R3, R7`. */
export function designatorText(designators: Designator[]): string {
  const items: string[] = [];
  let run: Designator[] = [];
  const flush = () => {
    if (run.length >= SHORTEST_RANGE) {
      items.push(`${nameOf(run[0] as Designator)}–${nameOf(run.at(-1) as Designator)}`);
    } else {
      items.push(...run.map(nameOf));
    }
    run = [];
  };
  for (const designator of designators) {
    const last = run.at(-1);
    if (last && (last.letters !== designator.letters || last.number + 1 !== designator.number)) {
      flush();
    }
    run.push(designator);
  }
  if (run.length > 0) flush();
  return items.join(", ");
}

/** One designator, trimmed and folded: `r01` and a fullwidth R1 are both `R1`. */
export function parseDesignator(text: string): Designator {
  const item = text.normalize("NFKC").trim();
  const read = DESIGNATOR.exec(item);
  if (!read) throw notADesignator(item);
  return designatorOf(item, (read[1] as string).toUpperCase(), read[2] as string);
}

function nameOf(designator: Designator): string {
  return `${designator.letters}${designator.number}`;
}

function compare(a: Designator, b: Designator): number {
  if (a.letters !== b.letters) return a.letters < b.letters ? -1 : 1;
  return a.number - b.number;
}

/** What a list has named so far; a range is checked before it is expanded, as the server does. */
class Reading {
  readonly designators: Designator[] = [];
  private readonly seen = new Set<string>();

  read(item: string) {
    const ends = item.split(DASHES);
    if (ends.length === 1) {
      this.name([parseDesignator(item)]);
      return;
    }
    const [first, second] = ends;
    if (ends.length !== 2 || !first || !second) throw notADesignator(item);
    const start = parseDesignator(first);
    const end = rangeEnd(item, start, second);
    if (end.letters !== start.letters || end.number <= start.number) {
      throw new Refused({ code: "invalid_range", item });
    }
    const named = [...this.seen]
      .map((name) => parseDesignator(name))
      .sort(compare)
      .find(
        (held) =>
          held.letters === start.letters &&
          held.number >= start.number &&
          held.number <= end.number,
      );
    if (named) throw namedTwice(named);
    if (this.seen.size + (end.number - start.number + 1) > MAX_DESIGNATORS) throw tooMany();
    const expanded: Designator[] = [];
    for (let number = start.number; number <= end.number; number += 1) {
      expanded.push({ letters: start.letters, number });
    }
    this.name(expanded);
  }

  private name(designators: Designator[]) {
    for (const designator of designators) {
      const key = nameOf(designator);
      if (this.seen.has(key)) throw namedTwice(designator);
      this.seen.add(key);
      this.designators.push(designator);
    }
    if (this.seen.size > MAX_DESIGNATORS) throw tooMany();
  }
}

/** A range's second end: a designator, or a bare number taking the start's letters. */
function rangeEnd(item: string, start: Designator, text: string): Designator {
  // Named as the whole range: `R1-0` is a range whose end isn't a designator.
  if (DIGITS.test(text)) return designatorOf(item, start.letters, text);
  try {
    return parseDesignator(text);
  } catch {
    throw notADesignator(item);
  }
}

/** The designator, or a refusal naming the item as it was typed. */
function designatorOf(item: string, letters: string, digits: string): Designator {
  const number = Number(digits.replace(/^0+/, "") || "0");
  if (letters.length > MAX_DESIGNATOR_LETTERS || number < 1 || number > MAX_DESIGNATOR_NUMBER) {
    throw notADesignator(item);
  }
  return { letters, number };
}

function notADesignator(item: string) {
  return new Refused({ code: "invalid_designator", item });
}

function namedTwice(designator: Designator) {
  return new Refused({ code: "repeated_designator", item: nameOf(designator) });
}

function tooMany() {
  return new Refused({ code: "too_many_designators", item: null });
}
