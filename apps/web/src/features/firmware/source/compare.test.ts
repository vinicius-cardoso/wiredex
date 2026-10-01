import type { SourceFile } from "@wiredex/api-client";
import { describe, expect, it } from "vitest";
import { config, sketch } from "../../../test/firmware";
import { aSourceFile } from "../../../test/server";
import { compareVersions, type DiffLine, type FileComparison, type Hunk } from "./compare";

/** Rows as a hunk holds them: unchanged, numbered in both versions; removed; added. */
function contextLine(oldNumber: number, newNumber: number, text: string): DiffLine {
  return { kind: "context", text, oldNumber, newNumber, noFinalNewline: false };
}

function removedLine(oldNumber: number, text: string, noFinalNewline = false): DiffLine {
  return { kind: "removed", text, oldNumber, newNumber: null, noFinalNewline };
}

function addedLine(newNumber: number, text: string, noFinalNewline = false): DiffLine {
  return { kind: "added", text, oldNumber: null, newNumber, noFinalNewline };
}

describe("compareVersions", () => {
  it("shows a changed sketch's hunk and counts its lines beside an unchanged header", () => {
    const changed = aSourceFile({
      id: sketch.id,
      path: sketch.path,
      content:
        '#include "config.h"\n\nvoid setup() {\n\tWire.begin(SDA_PIN, SCL_PIN);\n\tSerial.begin(115200);\n}\n',
    });

    // To lists its files in another order: a comparison keeps 13's, the sketch first.
    const { files, counts, lines } = compareVersions([sketch, config], [config, changed]);

    expect(files).toEqual([
      {
        path: "weather_station.ino",
        status: "changed",
        from: sketch,
        to: changed,
        added: 2,
        removed: 1,
        hunks: [
          {
            oldStart: 1,
            oldLines: 5,
            newStart: 1,
            newLines: 6,
            lines: [
              contextLine(1, 1, '#include "config.h"'),
              contextLine(2, 2, ""),
              contextLine(3, 3, "void setup() {"),
              removedLine(4, "\tWire.begin(SDA_PIN, SCL_PIN);  "),
              addedLine(4, "\tWire.begin(SDA_PIN, SCL_PIN);"),
              addedLine(5, "\tSerial.begin(115200);"),
              contextLine(5, 6, "}"),
            ],
          },
        ],
      },
      {
        path: "config.h",
        status: "unchanged",
        from: config,
        to: config,
        added: 0,
        removed: 0,
        hunks: [],
      },
    ]);
    expect(counts).toEqual({ added: 0, removed: 0, changed: 1, unchanged: 1 });
    expect(lines).toEqual({ added: 2, removed: 1 });
  });

  it("matches a path whose case alone changed, under To's name", () => {
    const before = aSourceFile({ path: "Config.H", content: config.content });
    const after = aSourceFile({ path: "config.h", content: config.content });

    const { files, counts } = compareVersions([before], [after]);

    expect(files).toEqual([
      {
        path: "config.h",
        status: "unchanged",
        from: before,
        to: after,
        added: 0,
        removed: 0,
        hunks: [],
      },
    ]);
    expect(counts).toEqual({ added: 0, removed: 0, changed: 0, unchanged: 1 });
  });

  it("shows an added file's lines all added and a removed file's all removed", () => {
    const header = aSourceFile({ path: "util.h", content: "int twice(int x);\n" });
    const source = aSourceFile({
      path: "util.cpp",
      content: "int twice(int x) {\n  return 2 * x;\n}\n",
    });

    const { files, counts, lines } = compareVersions([header], [source]);

    expect(files).toEqual([
      {
        path: "util.cpp",
        status: "added",
        from: null,
        to: source,
        added: 3,
        removed: 0,
        hunks: [
          {
            oldStart: 1,
            oldLines: 0,
            newStart: 1,
            newLines: 3,
            lines: [
              addedLine(1, "int twice(int x) {"),
              addedLine(2, "  return 2 * x;"),
              addedLine(3, "}"),
            ],
          },
        ],
      },
      {
        path: "util.h",
        status: "removed",
        from: header,
        to: null,
        added: 0,
        removed: 1,
        hunks: [
          {
            oldStart: 1,
            oldLines: 1,
            newStart: 1,
            newLines: 0,
            lines: [removedLine(1, "int twice(int x);")],
          },
        ],
      },
    ]);
    expect(counts).toEqual({ added: 1, removed: 1, changed: 0, unchanged: 0 });
    expect(lines).toEqual({ added: 3, removed: 1 });
  });

  it("flags a final line break added on the line it ends, not as a row of its own", () => {
    // 1.1.0's config.h ends without a line break; here it gains one.
    const after = aSourceFile({ path: "config.h", content: `${config.content}\n` });

    const [file] = compareVersions([config], [after]).files;

    expect(file).toMatchObject({ status: "changed", added: 1, removed: 1 });
    expect(file?.hunks).toEqual([
      {
        oldStart: 1,
        oldLines: 2,
        newStart: 1,
        newLines: 2,
        lines: [
          contextLine(1, 1, "#define SDA_PIN 21"),
          removedLine(2, "#define SCL_PIN 22", true),
          addedLine(2, "#define SCL_PIN 22"),
        ],
      },
    ]);
  });

  it("answers a file too costly to compare in time as changed, with no hunks", () => {
    // Two texts sharing no line, the costliest pair for a line diff: far past a millisecond.
    const text = (word: string) =>
      Array.from({ length: 5_000 }, (_, at) => `${word} ${at}`).join("\n");
    const before = aSourceFile({ path: "log.h", content: text("old") });
    const after = aSourceFile({ path: "log.h", content: text("new") });

    const { files, counts, lines } = compareVersions([before], [after], { timeoutMs: 1 });

    expect(files).toEqual([
      {
        path: "log.h",
        status: "changed",
        from: before,
        to: after,
        added: 0,
        removed: 0,
        hunks: null,
      },
    ]);
    expect(counts.changed).toBe(1);
    expect(lines).toEqual({ added: 0, removed: 0 });
  });

  it("lists both sides' files in 13's order: sketches first, then by folded path", () => {
    const from = ["src/b.cpp", "Zeta.ino", "lib/ｚ.h"].map((path) => aSourceFile({ path }));
    const to = ["alpha.INO", "README.md", "lib/😀.h", "src/b.cpp", "src/b.c"].map((path) =>
      aSourceFile({ path }),
    );

    const { files } = compareVersions(from, to);

    // Folded, `Zeta.ino` follows `alpha.INO`, and `README.md` follows `lib/`. By code point, as
    // Python orders them, the fullwidth ｚ (U+FF5A) comes before 😀 (U+1F600), whose surrogate
    // pair would sort first by UTF-16 unit; and a path comes before a longer one it begins.
    expect(files.map((file) => file.path)).toEqual([
      "alpha.INO",
      "Zeta.ino",
      "lib/ｚ.h",
      "lib/😀.h",
      "README.md",
      "src/b.c",
      "src/b.cpp",
    ]);
  });
});

/** Mulberry32: the same cases on every run, so a failing case fails again. */
function seeded(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let mixed = Math.imul(state ^ (state >>> 15), state | 1);
    mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), mixed | 61);
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4_294_967_296;
  };
}

function pick(random: () => number, items: readonly string[]): string {
  return items[Math.floor(random() * items.length)] ?? "";
}

// Few distinct lines, so a text repeats some and the diff has equal lines to choose between,
// with characters beyond ASCII among them.
const LINES = [
  "",
  "{",
  "}",
  "int count = 0;",
  "count++;",
  "// note",
  "  return count;",
  "°C",
  "😀",
];

/** A text's lines as 13 counts them, without their line breaks. */
function linesOf(text: string): string[] {
  if (text === "") return [];
  return (text.endsWith("\n") ? text.slice(0, -1) : text).split("\n");
}

function joined(lines: string[], finalBreak: boolean): string {
  const text = lines.join("\n");
  return finalBreak && lines.length > 0 ? `${text}\n` : text;
}

/** Up to twelve lines, ending with a line break more often than not. */
function textOf(random: () => number): string {
  const lines = Array.from({ length: Math.floor(random() * 13) }, () => pick(random, LINES));
  return joined(lines, random() < 0.7);
}

/** TEXT with one to three lines put in, taken out or replaced, its final break at times turned. */
function edited(random: () => number, text: string): string {
  const lines = linesOf(text);
  for (let edits = 1 + Math.floor(random() * 3); edits > 0; edits--) {
    const at = Math.floor(random() * (lines.length + 1));
    const edit = random();
    if (edit < 0.4) lines.splice(at, 0, pick(random, LINES));
    else if (edit < 0.7) lines.splice(at, 1);
    else lines.splice(at, 1, pick(random, LINES));
  }
  const turned = random() < 0.2;
  return joined(lines, turned !== text.endsWith("\n"));
}

/** Two hundred From and To texts of one file, To edited from From. */
function textPairs(seed: number): [string, string][] {
  const random = seeded(seed);
  return Array.from({ length: 200 }, (): [string, string] => {
    const before = textOf(random);
    return [before, edited(random, before)];
  });
}

/** The one file both texts make, compared. */
function comparedFile(before: string, after: string): FileComparison | undefined {
  const [file] = compareVersions(
    [aSourceFile({ content: before })],
    [aSourceFile({ content: after })],
  ).files;
  return file;
}

/**
 * Property 3's way forward: From's lines outside the hunks kept, each hunk's removed lines
 * dropped and its added ones put in, every line with its break unless it is flagged.
 */
function applied(text: string, hunks: Hunk[]): string {
  const lines = text.match(/[^\n]*\n|[^\n]+$/g) ?? []; // each with its own line break
  let result = "";
  let next = 0; // From's next line to keep, counted from 0
  for (const hunk of hunks) {
    result += lines.slice(next, hunk.oldStart - 1).join("");
    next = hunk.oldStart - 1;
    for (const line of hunk.lines) {
      if (line.kind !== "added") next++;
      if (line.kind !== "removed") result += line.noFinalNewline ? line.text : `${line.text}\n`;
    }
  }
  return result + lines.slice(next).join("");
}

// Paths whose folds differ, each given in its own case or in capitals, so one side may hold
// `CONFIG.H` where the other holds `config.h`; and few texts, so a pair is often equal.
const PATHS = ["app.ino", "Blink.ino", "config.h", "util.cpp", "lib/Sensor.h", "data.json"];
const TEXTS = ["", "void loop() {}\n", "#define LED 13", "x\ny\n"];

function filesOf(random: () => number): SourceFile[] {
  return PATHS.filter(() => random() < 0.5).map((path) =>
    aSourceFile({
      path: random() < 0.3 ? path.toUpperCase() : path,
      content: pick(random, TEXTS),
    }),
  );
}

function folded(file: { path: string }): string {
  return file.path.toLowerCase();
}

/**
 * Property 2: a comparison sorts every path once. For any two sets of files, every folded path
 * of either side appears exactly once, as added (only in To), removed (only in From), changed or
 * unchanged (in both), and it is unchanged exactly when the two texts are equal.
 *
 * **Validates: Requirements 4.1**
 */
describe("property 2: a comparison sorts every path once", () => {
  const random = seeded(2);
  const cases = Array.from({ length: 200 }, () => [filesOf(random), filesOf(random)] as const);

  it("lists each folded path once, unchanged exactly when its two texts are equal", () => {
    for (const [from, to] of cases) {
      const { files } = compareVersions(from, to);
      const sample = JSON.stringify({ from, to });
      const paths = new Set([...from, ...to].map(folded));
      expect(files.map(folded).toSorted(), sample).toEqual([...paths].toSorted());
      for (const file of files) {
        const old = from.find((held) => folded(held) === folded(file)) ?? null;
        const current = to.find((held) => folded(held) === folded(file)) ?? null;
        const status =
          old === null
            ? "added"
            : current === null
              ? "removed"
              : old.content === current.content
                ? "unchanged"
                : "changed";
        expect(file.status, sample).toBe(status);
        expect(file.from, sample).toBe(old);
        expect(file.to, sample).toBe(current);
      }
    }
  });
});

/**
 * Property 3: hunks turn From into To. For any changed file within the timeout, applying its
 * hunks to its From text gives its To text, and `added` and `removed` count its added and
 * removed lines.
 *
 * **Validates: Requirements 4.2, 8.5**
 */
describe("property 3: hunks turn From into To", () => {
  it("gives To back from From and the hunks, counting the lines they add and remove", () => {
    for (const [before, after] of textPairs(3)) {
      const file = comparedFile(before, after);
      const sample = JSON.stringify({ before, after });
      expect(file?.hunks, sample).not.toBeNull();
      const hunks = file?.hunks ?? [];
      expect(applied(before, hunks), sample).toBe(after);
      const rows = hunks.flatMap((hunk) => hunk.lines);
      expect(file?.added, sample).toBe(rows.filter((row) => row.kind === "added").length);
      expect(file?.removed, sample).toBe(rows.filter((row) => row.kind === "removed").length);
      // What was added less what was removed is what the file grew by.
      const grown = linesOf(after).length - linesOf(before).length;
      expect((file?.added ?? 0) - (file?.removed ?? 0), sample).toBe(grown);
    }
  });
});

/**
 * Property 4: line numbers point at their lines. For any changed file, every context or removed
 * line's old number names that line of From, and every context or added line's new number names
 * that line of To.
 *
 * **Validates: Requirements 4.2**
 */
describe("property 4: line numbers point at their lines", () => {
  it("numbers each line as it is in the version it comes from", () => {
    for (const [before, after] of textPairs(4)) {
      const file = comparedFile(before, after);
      const sample = JSON.stringify({ before, after });
      const old = linesOf(before);
      const current = linesOf(after);
      for (const line of file?.hunks?.flatMap((hunk) => hunk.lines) ?? []) {
        expect(line.oldNumber === null, sample).toBe(line.kind === "added");
        expect(line.newNumber === null, sample).toBe(line.kind === "removed");
        if (line.oldNumber !== null) expect(old[line.oldNumber - 1], sample).toBe(line.text);
        if (line.newNumber !== null) expect(current[line.newNumber - 1], sample).toBe(line.text);
      }
    }
  });
});
