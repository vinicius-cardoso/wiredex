/** What a source file is highlighted as, chosen by its extension (requirement 1.1). */
export type Language = "cpp" | "python" | "json" | "plain";

// A sketch is C++, and so are the C sources and headers beside it: one grammar reads them all.
// A Map rather than an object, so a name such as `notes.constructor` finds nothing inherited.
const EXTENSIONS: ReadonlyMap<string, Language> = new Map([
  ["ino", "cpp"],
  ["c", "cpp"],
  ["cc", "cpp"],
  ["cpp", "cpp"],
  ["cxx", "cpp"],
  ["h", "cpp"],
  ["hh", "cpp"],
  ["hpp", "cpp"],
  ["hxx", "cpp"],
  ["py", "python"],
  ["json", "json"],
]);

/**
 * Decision 2's table, extensions compared ignoring case. Only the last part of the path counts,
 * so a folder's dot never makes a file C++; anything else, `platformio.ini` and
 * `CMakeLists.txt` included, is plain text.
 */
export function languageOf(path: string): Language {
  const extension = /\.([^./]+)$/.exec(path)?.[1] ?? "";
  return EXTENSIONS.get(extension.toLowerCase()) ?? "plain";
}

/**
 * Past these a file is shown plain and unnumbered: highlighting it would build tens of
 * thousands of elements, and sketches are far smaller (decision 2).
 */
export const HIGHLIGHT_LIMITS = { lines: 5_000, bytes: 262_144 } as const;

/** Whether a file is highlighted and numbered, or shown plain (requirement 1.4). */
export function highlightable(file: { size: number; lines: number }): boolean {
  return file.lines <= HIGHLIGHT_LIMITS.lines && file.size <= HIGHLIGHT_LIMITS.bytes;
}
