import { describe, expect, it } from "vitest";
import { type HighlightedLine, highlightLines } from "./highlight";

const SKETCH = `#include <Wire.h>

// Read the sensor every second.
void loop() {
  if (millis() > 1000) {
    Serial.println("ready");
  }
}
`;

/** 13's count, `SourceText.lines`: none in an empty file, and a last line whether or not a
 * line break ends it. */
function linesOf(text: string): number {
  const breaks = text.split("\n").length - 1;
  return text === "" || text.endsWith("\n") ? breaks : breaks + 1;
}

/** Property 1's way back: each row's tokens joined, the rows by line breaks, and the final line
 * break when the text ends with one. */
function rejoined(rows: HighlightedLine[], finalBreak: boolean): string {
  const text = rows.map((row) => row.map((token) => token.text).join("")).join("\n");
  return finalBreak ? `${text}\n` : text;
}

/** The classes of the first token that is exactly TEXT. */
function classesOf(rows: HighlightedLine[], text: string): string | undefined {
  return rows.flat().find((token) => token.text === text)?.classes;
}

describe("highlightLines", () => {
  it("tells a sketch's types, keywords, strings and comments apart", () => {
    const rows = highlightLines(SKETCH, "cpp");
    // Lezer's C++ grammar reads `void` as a primitive type, as it reads `int`, not as a keyword.
    expect(classesOf(rows, "void")).toBe("tok-typeName");
    expect(classesOf(rows, "if")).toBe("tok-keyword");
    expect(classesOf(rows, '"ready"')).toBe("tok-string");
    expect(classesOf(rows, "// Read the sensor every second.")).toBe("tok-comment");
  });

  it("reads def as a keyword in Python", () => {
    const rows = highlightLines("def read():\n    return 42\n", "python");
    expect(classesOf(rows, "def")).toBe("tok-keyword");
  });

  it("tells a JSON key and a number apart", () => {
    const rows = highlightLines('{"interval": 1000}\n', "json");
    expect(classesOf(rows, '"interval"')).toBe("tok-propertyName");
    expect(classesOf(rows, "1000")).toBe("tok-number");
  });

  it("shows a sketch cut off halfway whole, styled where it parses", () => {
    const half = SKETCH.slice(0, SKETCH.indexOf('"ready"') + 3);
    const rows = highlightLines(half, "cpp");
    expect(rejoined(rows, false)).toBe(half);
    expect(rows).toHaveLength(linesOf(half));
    expect(classesOf(rows, "void")).toBe("tok-typeName");
    expect(classesOf(rows, "// Read the sensor every second.")).toBe("tok-comment");
  });

  it("styles nothing in plain text, one token a line", () => {
    expect(highlightLines("[env:uno]\n\nboard = uno", "plain")).toEqual([
      [{ text: "[env:uno]", classes: "" }],
      [],
      [{ text: "board = uno", classes: "" }],
    ]);
  });

  it("answers the lines 13 numbers, a final line break opening none", () => {
    expect(highlightLines("", "cpp")).toEqual([]);
    expect(highlightLines("\n", "cpp")).toEqual([[]]);
    expect(highlightLines("int x;", "cpp")).toHaveLength(1);
    expect(highlightLines("int x;\n", "cpp")).toHaveLength(1);
    expect(highlightLines("int x;\n\n", "cpp")).toHaveLength(2);
  });
});

/** Mulberry32: the same texts on every run, so a failing text fails again. */
function seeded(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let mixed = Math.imul(state ^ (state >>> 15), state | 1);
    mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), mixed | 61);
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4_294_967_296;
  };
}

// Pieces of the three languages, whole and broken, among line breaks and characters beyond
// ASCII, so the grammars meet both what parses and what doesn't, and tokens span lines.
const PIECES = [
  "void",
  "setup",
  "int count = 42;",
  "#include <Wire.h>",
  "#define LED 13",
  '"text"',
  "'c'",
  '"\\n"',
  "// note",
  "/* a",
  "*/",
  'R"(raw)"',
  "def",
  "class",
  "return",
  '"""doc',
  '"""',
  "# note",
  'f"{x}"',
  "@decorator",
  '{"key": [1, 2.5e3, null, true]}',
  '"',
  "(",
  ")",
  "{",
  "}",
  "[",
  "]",
  ":",
  ";",
  ",",
  "\\",
  " ",
  "    ",
  "\t",
  "\n",
  "\n",
  "\n",
  "é",
  "°C",
  "😀",
  "中",
];

function sourceText(random: () => number): string {
  let text = "";
  for (let count = Math.floor(random() * 40); count > 0; count--) {
    text +=
      random() < 0.2
        ? String.fromCharCode(0x20 + Math.floor(random() * 95))
        : (PIECES[Math.floor(random() * PIECES.length)] ?? "");
  }
  return text;
}

/**
 * Property 1: highlighting keeps the text. For any text and language, the rows are as many as
 * 13's `lines`, and joining their tokens, with the final line break when the text ends with one,
 * gives the text back.
 *
 * **Validates: Requirements 1.2, 1.3, 8.5**
 */
describe("property 1: highlighting keeps the text", () => {
  const random = seeded(14);
  const texts = Array.from({ length: 200 }, () => sourceText(random));

  it.each(["cpp", "python", "json", "plain"] as const)(
    "keeps every line and character as %s",
    (language) => {
      for (const text of texts) {
        const rows = highlightLines(text, language);
        const sample = JSON.stringify(text);
        expect(rows, sample).toHaveLength(linesOf(text));
        expect(rejoined(rows, text.endsWith("\n")), sample).toBe(text);
      }
    },
  );
});
