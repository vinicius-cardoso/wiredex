import type { Parser } from "@lezer/common";
import { parser as cpp } from "@lezer/cpp";
import { classHighlighter, highlightCode } from "@lezer/highlight";
import { parser as json } from "@lezer/json";
import { parser as python } from "@lezer/python";
import type { Language } from "./languages";

/** A run of text styled as one thing; `classes` is `classHighlighter`'s, "" when unstyled. */
export type Token = { text: string; classes: string };
export type HighlightedLine = Token[];

const PARSERS: Record<Exclude<Language, "plain">, Parser> = { cpp, python, json };

/**
 * The text as rows of tokens: exactly its lines, as 13 counts them, and exactly its characters
 * (property 1). The grammars recover from errors, so a sketch half written still comes back
 * whole, styled where it parses (requirement 1.3). Classes rather than inline styles, so the
 * site's own stylesheet colours them and the CSP's `style-src 'self'` holds (decision 1).
 */
export function highlightLines(text: string, language: Language): HighlightedLine[] {
  let row: HighlightedLine = [];
  const rows = [row];
  const putText = (piece: string, classes: string) => {
    row.push({ text: piece, classes });
  };
  const putBreak = () => {
    row = [];
    rows.push(row);
  };
  if (language === "plain") {
    // One unstyled token a line, and none on an empty line, as highlightCode leaves one.
    for (const [index, line] of text.split("\n").entries()) {
      if (index > 0) putBreak();
      if (line) putText(line, "");
    }
  } else {
    highlightCode(text, PARSERS[language].parse(text), classHighlighter, putText, putBreak);
  }
  // A final line break ends the last line rather than opening an empty one, and an empty file
  // has no line at all: the rows are the lines 13 numbers (SourceText.lines).
  if (text === "" || text.endsWith("\n")) rows.pop();
  return rows;
}
