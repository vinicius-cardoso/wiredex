import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { blink, config, sketch, v110, v120 } from "../../../test/firmware";
import { renderWithProviders } from "../../../test/render";
import { aSourceFile, aVersion } from "../../../test/server";
import { formatSize } from "../../files/sizes";
import { ComparisonView } from "./ComparisonView";

/** Each row of a file's table as its cells' text: old line, new line, change, text. */
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

describe("ComparisonView", () => {
  it("counts what changed, and shows each file's lines numbered, marked and highlighted", () => {
    const from = aVersion({ files: [blink.sketch, blink.header, blink.notes] });
    const to = aVersion({ files: [blink.changed, blink.source, blink.notes] });
    renderWithProviders(<ComparisonView from={from} to={to} />);

    const summary = screen.getByRole("list", { name: "Summary" });
    expect(
      within(summary)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "1 file changed",
      "1 file added",
      "1 file removed",
      "5 lines added",
      "2 lines removed",
    ]);
    expect(screen.getByText("Unchanged: notes.txt.")).toBeInTheDocument();
    // 13's order, sketches first; an unchanged file is named, not shown.
    const regions = screen.getAllByRole("region");
    expect(regions.map((region) => region.getAttribute("aria-label"))).toEqual([
      "app.ino, changed",
      "util.cpp, added",
      "util.h, removed",
    ]);

    const changed = screen.getByRole("region", { name: "app.ino, changed" });
    expect(within(changed).getByText("Changed")).toBeInTheDocument();
    const table = within(changed).getByRole("table", { name: "Lines changed in app.ino" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual(["Old line", "New line", "Change", "Text"]);
    expect(within(table).getByText("Lines 3–7 → 3–9")).toBeInTheDocument();
    // Three lines of context around the change, each numbered in the version it comes from.
    expect(rowsOf(table)).toEqual([
      ["3", "3", "", "void setup() {}"],
      ["4", "4", "", ""],
      ["5", "5", "", "void loop() {"],
      ["6", "", "−removed", "  delay(100);"],
      ["", "6", "+added", "  delay(250);"],
      ["", "7", "+added", "  if (ready()) return;"],
      ["", "8", "+added", "  blink();"],
      ["7", "9", "", "}"],
    ]);
    // The marks are words for a screen reader and a tint for the eye, never the tint alone.
    const [removed, added] = within(table).getAllByRole("row").slice(5, 7);
    expect(within(removed as HTMLElement).getByText("removed")).toHaveClass("sr-only");
    expect(within(removed as HTMLElement).getByText("−")).toHaveAttribute("aria-hidden", "true");
    expect(within(removed as HTMLElement).getAllByRole("cell")[0]).toHaveClass(
      "diff-gutter-removed",
    );
    expect(within(added as HTMLElement).getAllByRole("cell")[2]).toHaveClass("diff-gutter-added");
    // Highlighted in the file's language, as the viewer highlights it.
    expect(within(removed as HTMLElement).getByText("100")).toHaveClass("tok-number");
    expect(within(table).getByText("return")).toHaveClass("tok-keyword");

    const addedFile = screen.getByRole("region", { name: "util.cpp, added" });
    expect(within(addedFile).getByText("Lines 1–2, all added")).toBeInTheDocument();
    expect(rowsOf(within(addedFile).getByRole("table"))).toEqual([
      ["", "1", "+added", '#include "util.h"'],
      ["", "2", "+added", "int led = LED;"],
    ]);
    const removedFile = screen.getByRole("region", { name: "util.h, removed" });
    expect(within(removedFile).getByText("Line 1, removed")).toBeInTheDocument();
    expect(rowsOf(within(removedFile).getByRole("table"))).toEqual([
      ["1", "", "−removed", "#define LED 2"],
    ]);
  });

  it("says when the two versions hold the same files with the same text", () => {
    renderWithProviders(<ComparisonView from={v110} to={v120} />);

    expect(
      screen.getByText("The two versions hold the same files, with the same text."),
    ).toBeInTheDocument();
    expect(screen.getByText(`Unchanged: ${sketch.path} and ${config.path}.`)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Summary" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });

  it("says a final line break added on the line it was missing from", () => {
    const from = aVersion({ files: [aSourceFile({ path: "config.h", content: "#define A 1" })] });
    const to = aVersion({ files: [aSourceFile({ path: "config.h", content: "#define A 1\n" })] });
    renderWithProviders(<ComparisonView from={from} to={to} />);

    const table = screen.getByRole("table", { name: "Lines changed in config.h" });
    expect(rowsOf(table)).toEqual([
      ["1", "", "−removed", "#define A 1 No line break at the end"],
      ["", "1", "+added", "#define A 1"],
    ]);
  });

  it("shows a file too costly to compare in time by its two sizes", () => {
    // Two texts sharing no line, the costliest pair for a line diff: far past a millisecond.
    const text = (word: string) =>
      Array.from({ length: 5_000 }, (_, at) => `${word} ${at}`).join("\n");
    const before = aSourceFile({ path: "log.h", content: text("old") });
    const after = aSourceFile({ path: "log.h", content: text("newer") });
    renderWithProviders(
      <ComparisonView
        from={aVersion({ files: [before] })}
        to={aVersion({ files: [after] })}
        timeoutMs={1}
      />,
    );

    const file = screen.getByRole("region", { name: "log.h, changed" });
    expect(file).toHaveTextContent(
      `These changes took too long to work out, so only the sizes are shown: ${formatSize(before.size, "en")} before, ${formatSize(after.size, "en")} after.`,
    );
    expect(within(file).queryByRole("table")).not.toBeInTheDocument();
  });
});
