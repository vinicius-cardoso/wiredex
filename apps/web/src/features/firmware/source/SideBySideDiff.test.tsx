import { act, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { blink } from "../../../test/firmware";
import { setWideScreen } from "../../../test/match-media";
import { renderWithProviders } from "../../../test/render";
import { aSourceFile, aVersion } from "../../../test/server";
import { ComparisonView } from "./ComparisonView";
import { type DiffLine, sideBySide } from "./compare";

/** Each row as its cells' text: old line, change, old text, then the same three of the new. */
function rowsOf(table: HTMLElement): string[][] {
  return within(table)
    .getAllByRole("row")
    .map((row) =>
      within(row)
        .queryAllByRole("cell")
        .map((cell) => cell.textContent ?? ""),
    )
    .filter((cells) => cells.length > 0);
}

function line(
  kind: DiffLine["kind"],
  text: string,
  oldNumber: number | null,
  newNumber: number | null,
) {
  return { kind, text, oldNumber, newNumber, noFinalNewline: false };
}

describe("sideBySide", () => {
  it("faces each line removed with the line added in its place, the rest with nothing", () => {
    const kept = line("context", "void loop() {", 1, 1);
    const removed = [line("removed", "a", 2, null), line("removed", "b", 3, null)];
    const added = [line("added", "c", null, 2)];
    const end = line("context", "}", 4, 3);
    const more = line("added", "// end", null, 4);
    const hunk = { oldStart: 1, oldLines: 4, newStart: 1, newLines: 4 };

    expect(sideBySide({ ...hunk, lines: [kept, ...removed, ...added, end, more] })).toEqual([
      { old: kept, new: kept },
      { old: removed[0], new: added[0] },
      { old: removed[1], new: null },
      { old: end, new: end },
      { old: null, new: more },
    ]);
  });
});

describe("SideBySideDiff", () => {
  it("shows the old version beside the new on a wide window, changed words marked", () => {
    setWideScreen(true);
    const from = aVersion({ files: [blink.sketch, blink.header] });
    const to = aVersion({ files: [blink.changed, blink.source] });
    renderWithProviders(<ComparisonView from={from} to={to} />);

    const changed = screen.getByRole("region", { name: "app.ino, changed" });
    const table = within(changed).getByRole("table", { name: "Lines changed in app.ino" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual(["Old line", "Change", "Old version", "New line", "Change", "New version"]);
    expect(within(table).getByText("Lines 3–7 → 3–9")).toBeInTheDocument();
    expect(rowsOf(table)).toEqual([
      ["3", "", "void setup() {}", "3", "", "void setup() {}"],
      ["4", "", "", "4", "", ""],
      ["5", "", "void loop() {", "5", "", "void loop() {"],
      // The line that changed faces what replaced it; the two added after it face nothing.
      ["6", "−removed", "  delay(100);", "6", "+added", "  delay(250);"],
      ["", "", "", "7", "+added", "  if (ready()) return;"],
      ["", "", "", "8", "+added", "  blink();"],
      ["7", "", "}", "9", "", "}"],
    ]);

    const [replaced, extra] = within(table).getAllByRole("row").slice(5, 7);
    const cells = within(replaced as HTMLElement).getAllByRole("cell");
    // A tinted gutter and line on each side, and the mark in words for a screen reader.
    expect(cells[0]).toHaveClass("diff-gutter-removed");
    expect(cells[2]).toHaveClass("diff-line-removed");
    expect(cells[3]).toHaveClass("diff-gutter-added");
    expect(cells[5]).toHaveClass("diff-line-added");
    expect(within(cells[1] as HTMLElement).getByText("removed")).toHaveClass("sr-only");
    // Only the number changed inside the line, and it keeps its syntax colour.
    expect(within(cells[2] as HTMLElement).getByText("100")).toHaveClass(
      "tok-number",
      "diff-word-removed",
    );
    expect(within(cells[5] as HTMLElement).getByText("250")).toHaveClass(
      "tok-number",
      "diff-word-added",
    );
    expect(within(cells[5] as HTMLElement).getByText("delay")).not.toHaveClass("diff-word-added");
    // Where the old version has no line, its side is hatched rather than blank.
    const blank = within(extra as HTMLElement).getAllByRole("cell");
    expect(blank.slice(0, 3).every((cell) => cell.classList.contains("diff-filler"))).toBe(true);
    expect(blank[5]).toHaveClass("diff-line-added");

    // An added file fills the right pane only, a removed one the left.
    const added = screen.getByRole("region", { name: "util.cpp, added" });
    expect(rowsOf(within(added).getByRole("table"))).toEqual([
      ["", "", "", "1", "+added", '#include "util.h"'],
      ["", "", "", "2", "+added", "int led = LED;"],
    ]);
    const removed = screen.getByRole("region", { name: "util.h, removed" });
    expect(rowsOf(within(removed).getByRole("table"))).toEqual([
      ["1", "−removed", "#define LED 2", "", "", ""],
    ]);
  });

  it("marks no words on a line replaced by a different one, and notes a missing line break", () => {
    setWideScreen(true);
    const from = aVersion({
      files: [aSourceFile({ path: "config.h", content: "pinMode(LED_PIN, OUTPUT);" })],
    });
    const to = aVersion({
      files: [aSourceFile({ path: "config.h", content: "Serial.begin(115200);\n" })],
    });
    renderWithProviders(<ComparisonView from={from} to={to} />);

    const table = screen.getByRole("table", { name: "Lines changed in config.h" });
    expect(rowsOf(table)).toEqual([
      [
        "1",
        "−removed",
        "pinMode(LED_PIN, OUTPUT); No line break at the end",
        "1",
        "+added",
        "Serial.begin(115200);",
      ],
    ]);
    expect(table.querySelector(".diff-word-removed, .diff-word-added")).toBeNull();
  });

  it("goes back to one column when the window narrows", () => {
    setWideScreen(true);
    const from = aVersion({ files: [blink.sketch] });
    const to = aVersion({ files: [blink.changed] });
    renderWithProviders(<ComparisonView from={from} to={to} />);
    expect(screen.getAllByRole("columnheader")).toHaveLength(6);

    act(() => setWideScreen(false));
    expect(screen.getAllByRole("columnheader").map((header) => header.textContent)).toEqual([
      "Old line",
      "New line",
      "Change",
      "Text",
    ]);
  });
});
