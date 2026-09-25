/**
 * Reading a pin table that was pasted: a spreadsheet copy, a datasheet's table, a semicolon
 * list from a spreadsheet in a comma-decimal locale. Pure functions, no React.
 *
 * A 40-pin board is a paste, not forty forms (requirement 6.2), and what is pasted is never
 * clean: a header line, rows that stop after two columns, a type column spelled `PWR`. So
 * this reads text into rows and marks what it had to interpret, leaving the row itself alone:
 * the preview shows the marks, the owner corrects them, and only then is anything saved.
 *
 * Nothing here validates a pin. Whether `A1` is a number and `3V3` a voltage is the domain's
 * to say, and its refusal names the row and the cell (requirement 3.1), so a second opinion
 * in the browser could only disagree with it.
 */

import { pinTypeFromLabel, pinTypeOf } from "./pinTypes";

/**
 * What a row needs a second look at. The preview turns each into its own sentence from
 * `catalog.pinout.paste.*`; the reader stays free of translations.
 */
export type PasteWarning = "unknownType" | "typeGuessed";

/** One pasted line, as the editor will hold it: five cells of text plus what to review. */
export type ParsedRow = {
  number: string;
  label: string;
  /** One of the eight type names, or the text as pasted when `unknownType` is warned. */
  type: string;
  functions: string[];
  voltage: string;
  warnings: PasteWarning[];
};

// Tab first: a spreadsheet copy is tab-separated and its cells may well hold a comma. Then
// `;`, what a spreadsheet writes where the comma is the decimal point, then `,`.
const SEPARATORS = ["\t", ";", ","] as const;

type Separator = (typeof SEPARATORS)[number];

// A pin number in the charset the domain allows, with a digit somewhere in it: `1`, `40`,
// `A1`, `P1.3`. The digit is what tells a first cell of data from a column name.
const PIN_NUMBER = /^(?=.*\d)[a-z0-9_.+-]{1,16}$/i;

// Column names, folded to ASCII and matched as substrings, in both languages the app speaks:
// `pin` catches `Pin #` and `Pino`, `func` catches `Function`, `Funções` and `Funcao`.
const COLUMN_WORDS = [
  "pin",
  "name",
  "nome",
  "label",
  "rotulo",
  "type",
  "tipo",
  "func",
  "volt",
  "tensao",
];

/**
 * The pasted text as rows, in the order it was pasted, one per line that holds anything
 * (requirements 6.2 to 6.4). Columns are number, label, type, functions and voltage: a line
 * that stops early leaves the rest empty, and anything past the fifth cell is dropped.
 */
export function parsePinTable(text: string): ParsedRow[] {
  const lines = text.split(/\r?\n/).filter((line) => line.trim() !== "");
  // One separator for the whole table, read off the first line: a table doesn't change
  // separator halfway, and a later line that holds none is a one-column row, not a new rule.
  const separator = separatorOf(lines[0] ?? "");
  const rows = lines.map((line) => line.split(separator).map((cell) => cell.trim()));
  const [head, ...rest] = rows;
  // Only ever the first line, and only when it reads like column names (requirement 6.3).
  const body = head !== undefined && looksLikeHeader(head) ? rest : rows;
  return body.map((cells) => rowOf(cells, separator));
}

function separatorOf(line: string): Separator {
  return SEPARATORS.find((candidate) => line.includes(candidate)) ?? ",";
}

/**
 * A first line is a header when it doesn't start with something that could be a pin number
 * and one of its cells is a column name. Both halves are needed: a line starting at `1` is
 * data whatever words follow it, since a label may well be `TYPE_SEL`, and a table whose
 * first pin is `EP` has no column name to find.
 */
function looksLikeHeader(cells: string[]): boolean {
  const [first = ""] = cells;
  return !PIN_NUMBER.test(first) && cells.some(namesAColumn);
}

function namesAColumn(cell: string): boolean {
  const folded = cell
    .normalize("NFD")
    .replace(/\p{Mark}/gu, "")
    .toLowerCase();
  return COLUMN_WORDS.some((word) => folded.includes(word));
}

function rowOf(cells: string[], separator: Separator): ParsedRow {
  // Missing trailing cells are empty, never a row thrown away (requirement 6.4).
  const [number = "", label = "", type = "", functions = "", voltage = ""] = cells;
  const read = readType(type, label);
  return {
    number,
    label,
    type: read.type,
    functions: splitFunctions(functions, separator),
    voltage,
    warnings: read.warnings,
  };
}

/** The type cell mapped, guessed from the label, or kept as pasted and marked. */
function readType(cell: string, label: string): { type: string; warnings: PasteWarning[] } {
  if (cell === "") {
    const guessed = pinTypeFromLabel(label);
    // A guess is marked as a guess (requirement 6.6), so the row that reads `VCC` but is
    // really an input is one the preview asks about instead of one that slips through.
    if (guessed === null) return { type: "", warnings: [] };
    return { type: guessed, warnings: ["typeGuessed"] };
  }
  const known = pinTypeOf(cell);
  // An unknown spelling keeps its text so the preview can show what was pasted next to the
  // mark, instead of quietly calling it `other` (requirement 6.5).
  if (known === null) return { type: cell, warnings: ["unknownType"] };
  return { type: known, warnings: [] };
}

/**
 * Alternate functions that share one cell: `SDA/MOSI`, `SDA MOSI`, `SDA;MOSI` (requirement
 * 6.7). The comma splits too, except in a comma-separated table, where it is the separator
 * and has already done its splitting.
 */
function splitFunctions(cell: string, separator: Separator): string[] {
  const between = separator === "," ? /[/;|\s]+/ : /[/;|,\s]+/;
  return cell.split(between).filter((function_) => function_ !== "");
}
