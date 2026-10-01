import type { SourceFile } from "@wiredex/api-client";
import { type StructuredPatchHunk, structuredPatch } from "diff";

/** Where a file stands from one version to the other (requirement 4.1). */
export type FileStatus = "added" | "removed" | "changed" | "unchanged";

export type DiffLine = {
  kind: "context" | "added" | "removed";
  text: string; // without its line break
  oldNumber: number | null; // null on an added line
  newNumber: number | null; // null on a removed line
  // jsdiff's "\ No newline at end of file" after this line, kept as a flag rather than a row, so
  // a final line break added or removed reads as "no line break at the end" on the line it follows
  noFinalNewline: boolean;
};

/** Changed lines with up to three unchanged ones around them, numbered as jsdiff numbers them:
 * a side with no lines, such as an added file's From, starts at line 1 and holds 0. */
export type Hunk = {
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  lines: DiffLine[];
};

export type FileComparison = {
  path: string; // To's path, or From's for a removed file
  status: FileStatus;
  from: SourceFile | null;
  to: SourceFile | null;
  hunks: Hunk[] | null; // null: past the timeout (requirement 4.9)
  added: number; // 0 when hunks is null: those lines were never counted
  removed: number;
};

export type Comparison = {
  files: FileComparison[]; // 13's order over both sides: .ino first, then by folded path
  counts: Record<FileStatus, number>;
  lines: { added: number; removed: number };
};

/** Requirement 4.2's context; jsdiff's own default is four lines. */
const CONTEXT = 3;
/** Requirement 4.9's second, past which a file is shown changed with its sizes. */
const TIMEOUT_MS = 1_000;

/**
 * Decisions 7 and 8: files matched by folded path, lines by jsdiff's `structuredPatch`. A file
 * on one side only is compared with an empty text, so its lines all read as added or removed
 * (requirement 4.3); the timeout counts for each file on its own.
 */
export function compareVersions(
  from: SourceFile[],
  to: SourceFile[],
  options: { timeoutMs?: number } = {},
): Comparison {
  const timeoutMs = options.timeoutMs ?? TIMEOUT_MS;
  const before = new Set(from.map((file) => fold(file.path)));
  const after = new Map(to.map((file) => [fold(file.path), file]));
  const files = [
    ...from.map((old) => {
      const current = after.get(fold(old.path)) ?? null;
      return compared(current ?? old, old, current, timeoutMs);
    }),
    ...to
      .filter((file) => !before.has(fold(file.path)))
      .map((file) => compared(file, null, file, timeoutMs)),
  ].sort((a, b) => listingOrder(fold(a.path), fold(b.path)));
  const counts = { added: 0, removed: 0, changed: 0, unchanged: 0 };
  const lines = { added: 0, removed: 0 };
  for (const file of files) {
    counts[file.status]++;
    lines.added += file.added;
    lines.removed += file.removed;
  }
  return { files, counts, lines };
}

/** One path's two sides, NAMED by the file whose path the comparison shows. */
function compared(
  named: SourceFile,
  from: SourceFile | null,
  to: SourceFile | null,
  timeoutMs: number,
): FileComparison {
  const status: FileStatus =
    from === null
      ? "added"
      : to === null
        ? "removed"
        : from.content === to.content
          ? "unchanged"
          : "changed";
  const hunks =
    status === "unchanged" ? [] : hunksOf(from?.content ?? "", to?.content ?? "", timeoutMs);
  const lines = hunks?.flatMap((hunk) => hunk.lines) ?? [];
  return {
    path: named.path,
    status,
    from,
    to,
    hunks,
    added: lines.filter((line) => line.kind === "added").length,
    removed: lines.filter((line) => line.kind === "removed").length,
  };
}

/** jsdiff's hunks, or null when they take longer than the timeout to compute. */
function hunksOf(oldText: string, newText: string, timeoutMs: number): Hunk[] | null {
  // The names only head a patch's text, which nothing here writes.
  const patch = structuredPatch("", "", oldText, newText, undefined, undefined, {
    context: CONTEXT,
    timeout: timeoutMs,
  });
  return patch ? patch.hunks.map(numbered) : null;
}

/**
 * A hunk's lines as rows, each numbered in the version it comes from (requirement 4.2). jsdiff
 * writes `\ No newline at end of file` as a line of its own after the line a text ends on
 * without a break; the row before it takes it as its flag instead.
 */
function numbered(hunk: StructuredPatchHunk): Hunk {
  const lines: DiffLine[] = [];
  let oldNumber = hunk.oldStart;
  let newNumber = hunk.newStart;
  for (const [index, line] of hunk.lines.entries()) {
    if (line.startsWith("\\")) continue;
    const kind = line.startsWith("+") ? "added" : line.startsWith("-") ? "removed" : "context";
    lines.push({
      kind,
      text: line.slice(1),
      oldNumber: kind === "added" ? null : oldNumber,
      newNumber: kind === "removed" ? null : newNumber,
      noFinalNewline: hunk.lines[index + 1]?.startsWith("\\") === true,
    });
    if (kind !== "added") oldNumber++;
    if (kind !== "removed") newNumber++;
  }
  const { oldStart, oldLines, newStart, newLines } = hunk;
  return { oldStart, oldLines, newStart, newLines, lines };
}

/**
 * A path as 13 compares it: `SourcePath.fold`, Python's `str.lower()`, the unique index's own
 * expression. `toLowerCase()` maps the same way, Unicode's full lowercase with no locale and the
 * final sigma included, but from the browser's own Unicode tables: where those are newer than
 * Python 3.14's Unicode 16.0, letters encoded since then fold here and not there.
 */
function fold(path: string): string {
  return path.toLowerCase();
}

/** 13's `_listing_order` over folded paths: sketches first, then each group by path. */
function listingOrder(a: string, b: string): number {
  return Number(!a.endsWith(".ino")) - Number(!b.endsWith(".ino")) || byCodePoint(a, b);
}

/**
 * Python's order for strings, by code point. JavaScript's `<` compares UTF-16 units, which puts
 * a character past U+FFFF, a surrogate pair, before one from U+E000 to U+FFFF; lifting the
 * surrogates above those units gives the code points' order back.
 */
function byCodePoint(a: string, b: string): number {
  for (let index = 0; index < Math.min(a.length, b.length); index++) {
    const left = rank(a.charCodeAt(index));
    const right = rank(b.charCodeAt(index));
    if (left !== right) return left - right;
  }
  return a.length - b.length;
}

function rank(unit: number): number {
  if (unit >= 0xe000) return unit - 0x800;
  if (unit >= 0xd800) return unit + 0x2000;
  return unit;
}
