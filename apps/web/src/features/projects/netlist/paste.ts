import type { WireColor } from "@wiredex/api-client";

/** Why a pasted line can't be sent as it is. */
export type WiringProblem = "noPins" | "needsTwo";

/** One pasted line, read: what it names, the pins it joins, and the line it came from. */
export type WiringRow = {
  line: number;
  name: string | null;
  color: WireColor | null;
  pins: string;
  notes: string | null;
  problem: WiringProblem | null;
};

/**
 * A pasted table of wiring, read. `between` holds the two designators of a table that lists
 * the connections between two parts, and is null for a table of whole nets.
 */
export type ParsedWiring = { between: [string, string] | null; rows: WiringRow[] };

/** As many lines as the API takes in one paste. */
export const MOST_LINES = 500;

/** A colour as someone writes it, in either language the app speaks. */
const COLOR_WORDS: Record<string, WireColor> = {
  black: "black",
  preto: "black",
  preta: "black",
  brown: "brown",
  marrom: "brown",
  red: "red",
  vermelho: "red",
  vermelha: "red",
  orange: "orange",
  laranja: "orange",
  yellow: "yellow",
  amarelo: "yellow",
  amarela: "yellow",
  green: "green",
  verde: "green",
  blue: "blue",
  azul: "blue",
  violet: "violet",
  purple: "violet",
  violeta: "violet",
  roxo: "violet",
  roxa: "violet",
  grey: "grey",
  gray: "grey",
  cinza: "grey",
  white: "white",
  branco: "white",
  branca: "white",
  pink: "pink",
  rosa: "pink",
};

const HEADER_WORDS = new Set([
  "net",
  "nets",
  "name",
  "rede",
  "redes",
  "nome",
  "pin",
  "pins",
  "pino",
  "pinos",
  "color",
  "colour",
  "cor",
  "notes",
  "notas",
  "wire",
  "fio",
]);

// A designator, a dot and a pin. The designator starts with a letter here, so a net called
// "3.3V" isn't taken for a pin.
const REFERENCE = /^[A-Za-z][\w-]*\.[^\s.,;][^\s,;]*$/;
const DESIGNATOR = /^[A-Za-z][\w-]*$/;

type Line = { number: number; text: string };

/**
 * Reads pasted wiring in one of two shapes.
 *
 * Whole nets, one per line: a name, the pins and a colour, in any order, as in
 * `SDA; U1.25, U2.3; blue`. The pins are what gives the line away, so the name and the colour
 * are both optional.
 *
 * Between two parts: the first line names two designators (`U1; U2`), and every line after it
 * one pin of each (`25; SDA`), with a name and a colour after them if the line has any.
 *
 * Cells are split by tabs or semicolons; a line with neither is split by its commas.
 */
export function parseWiring(text: string): ParsedWiring {
  const lines = text
    .split(/\r?\n/)
    .map((line, at) => ({ number: at + 1, text: line.trim() }))
    .filter((line) => line.text !== "");
  const [first, ...rest] = lines;
  if (!first) return { between: null, rows: [] };

  const between = endsOf(first.text);
  if (between) return { between, rows: rest.map((line) => pairOf(line, between)) };

  const body = isHeader(first.text) ? rest : lines;
  return { between: null, rows: body.map(netOf) };
}

/** A line's cells. Commas split a pin list, so they only split cells where the caller says a
 *  cell holds no list, or where the line has no tab or semicolon to go by. */
function cellsOf(text: string, alsoCommas: boolean): string[] {
  const separator = /[\t;]/.test(text) ? (alsoCommas ? /[\t;,]/ : /[\t;]/) : /,/;
  return text
    .split(separator)
    .map((cell) => cell.trim())
    .filter((cell) => cell !== "");
}

function isHeader(text: string): boolean {
  return cellsOf(text, true).every((cell) => HEADER_WORDS.has(cell.toLowerCase()));
}

/** The two designators a first line names, when that is all it starts with. */
function endsOf(text: string): [string, string] | null {
  if (isHeader(text)) return null;
  const [from, to, ...others] = cellsOf(text, true);
  if (!from || !to) return null;
  const bare = (cell: string) => DESIGNATOR.test(cell) && !(cell.toLowerCase() in COLOR_WORDS);
  if (!bare(from) || !bare(to)) return null;
  // Anything after the two designators is the heading of a name or colour column.
  if (!others.every((cell) => HEADER_WORDS.has(cell.toLowerCase()))) return null;
  return [from.toUpperCase(), to.toUpperCase()];
}

function pairOf({ number, text }: Line, [from, to]: [string, string]): WiringRow {
  const [near, far, ...others] = cellsOf(text, true);
  const extras = sorted(others);
  if (!near || !far) return { line: number, pins: "", ...extras, problem: "needsTwo" };
  return { line: number, pins: `${from}.${near}, ${to}.${far}`, ...extras, problem: null };
}

function netOf({ number, text }: Line): WiringRow {
  const pins: string[] = [];
  const others: string[] = [];
  for (const cell of cellsOf(text, false)) {
    const items = cell.split(/[\s,]+/).filter(Boolean);
    if (items.every((item) => REFERENCE.test(item))) pins.push(...items);
    else others.push(cell);
  }
  return {
    line: number,
    pins: pins.join(", "),
    ...sorted(others),
    problem: pins.length === 0 ? "noPins" : null,
  };
}

/** The cells that aren't pins: the first colour word, the first other cell as the name, and
 *  whatever is left as notes. */
function sorted(cells: string[]): Pick<WiringRow, "name" | "color" | "notes"> {
  let name: string | null = null;
  let color: WireColor | null = null;
  const notes: string[] = [];
  for (const cell of cells) {
    const word = COLOR_WORDS[cell.toLowerCase()];
    if (word && color === null) color = word;
    else if (name === null) name = cell;
    else notes.push(cell);
  }
  return { name, color, notes: notes.length > 0 ? notes.join("; ") : null };
}
