import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { codeOf, config, sketch, V120, weatherStationWith } from "../../test/firmware";
import { renderWithProviders } from "../../test/render";
import { acceptFirmwareWrites, aSourceFile, aVersion } from "../../test/server";
import { SourceFiles } from "./SourceFiles";

describe("SourceFiles", () => {
  it("shows each file's text as stored, under its path with its size and line count", () => {
    const released = aVersion({ status: "released", files: [sketch, config] });
    renderWithProviders(<SourceFiles version={released} framework="arduino" />);
    const files = screen.getByRole("region", { name: "Source files" });
    expect(files).toHaveTextContent(`2 files · ${sketch.size + config.size} B`);
    const index = within(files).getByRole("navigation", { name: "Files in this version" });
    const links = within(index).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(["weather_station.ino", "config.h"]);
    expect(links[1]).toHaveAttribute("href", `#file-${config.id}`);
    const first = within(files).getByRole("region", { name: "weather_station.ino" });
    expect(first).toHaveTextContent(`${sketch.size} B · 5 lines`);
    // Tabs, trailing spaces and the final line break stay as they were written.
    const box = within(first).getByRole("group", { name: "weather_station.ino" });
    expect(codeOf(box)).toBe(sketch.content);
    const second = within(files).getByRole("region", { name: "config.h" });
    expect(second).toHaveAttribute("id", `file-${config.id}`);
    expect(second).toHaveTextContent(`${config.size} B · 2 lines`);
    expect(codeOf(within(second).getByRole("group", { name: "config.h" }))).toBe(config.content);
    // A release is read only.
    expect(within(files).queryByRole("button")).not.toBeInTheDocument();
    expect(within(files).queryByLabelText("Add files from the computer")).not.toBeInTheDocument();
  });

  it("lists no index for a single file, and counts an empty one as empty", () => {
    const empty = aSourceFile({ path: "main.py", content: "" });
    renderWithProviders(
      <SourceFiles version={aVersion({ files: [empty] })} framework="micropython" />,
    );
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    const file = screen.getByRole("region", { name: "main.py" });
    expect(file).toHaveTextContent("0 B · empty");
    expect(file).toHaveTextContent("This file is empty.");
    expect(within(file).queryByRole("group")).not.toBeInTheDocument();
  });

  it("says so when the version has no file yet", () => {
    renderWithProviders(<SourceFiles version={aVersion()} framework="arduino" />);
    expect(screen.getByRole("region", { name: "Source files" })).toHaveTextContent(
      "No source files yet.",
    );
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("wraps long lines when asked, and remembers it on this device", async () => {
    const user = userEvent.setup();
    const released = aVersion({ status: "released", files: [sketch, config] });
    const { unmount } = renderWithProviders(<SourceFiles version={released} framework="arduino" />);
    const wrap = screen.getByRole("switch", { name: "Wrap long lines" });
    expect(wrap).not.toBeChecked();
    // Every file's box wraps or scrolls together.
    const codes = () =>
      screen.getAllByRole("group").map((box) => box.querySelector("code") as HTMLElement);
    for (const code of codes()) expect(code).not.toHaveClass("whitespace-pre-wrap");

    await user.click(wrap);
    expect(wrap).toBeChecked();
    for (const code of codes()) expect(code).toHaveClass("whitespace-pre-wrap");
    expect(localStorage.getItem("wiredex.firmware.wrap")).toBe("on");

    // Back on this device later, the files wrap from the start.
    unmount();
    renderWithProviders(<SourceFiles version={released} framework="arduino" />);
    const again = screen.getByRole("switch", { name: "Wrap long lines" });
    expect(again).toBeChecked();
    for (const code of codes()) expect(code).toHaveClass("whitespace-pre-wrap");
    await user.click(again);
    for (const code of codes()) expect(code).not.toHaveClass("whitespace-pre-wrap");
    expect(localStorage.getItem("wiredex.firmware.wrap")).toBe("off");
  });

  it("shows a file past the highlighter's limits plain and unnumbered, saying why", () => {
    const table = aSourceFile({ path: "table.h", content: "0x00,\n".repeat(5_001) });
    renderWithProviders(
      <SourceFiles
        version={aVersion({ status: "released", files: [table] })}
        framework="arduino"
      />,
    );
    const box = screen.getByRole("group", { name: "table.h" });
    expect(box).toHaveAccessibleDescription(
      "This file is over 5,000 lines or 256.0 KB, so it is shown as plain text, without highlighting or line numbers.",
    );
    expect(codeOf(box)).toBe(table.content);
    expect(box.textContent).toBe(table.content);
  });

  it("shows a draft against its limits, and asks in place before removing a file", async () => {
    const user = userEvent.setup();
    const draft = aVersion({ id: V120, version: "1.2.0", files: [sketch, config] });
    const writes = acceptFirmwareWrites([weatherStationWith([draft])], { versions: [draft] });
    renderWithProviders(<SourceFiles version={draft} framework="arduino" />);
    const files = screen.getByRole("region", { name: "Source files" });
    expect(files).toHaveTextContent(`${sketch.size + config.size} B of 1.0 MB · 2 of 100 files`);
    expect(within(files).getByRole("button", { name: "Edit weather_station.ino" })).toBeVisible();
    // A draft's files are shown as a release's are.
    expect(within(files).getByRole("group", { name: "config.h" })).toBeVisible();

    await user.click(within(files).getByRole("button", { name: "Remove config.h" }));
    const file = within(files).getByRole("region", { name: "config.h" });
    expect(file).toHaveTextContent("Remove config.h from this draft?");
    // A stray Enter keeps the file.
    expect(within(file).getByRole("button", { name: "Keep it" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(within(files).getByRole("button", { name: "Remove config.h" })).toHaveFocus();
    expect(writes.fileRemovals).toHaveLength(0);

    await user.click(within(files).getByRole("button", { name: "Remove config.h" }));
    await user.click(within(files).getByRole("button", { name: "Yes, remove it" }));
    await waitFor(() =>
      expect(writes.fileRemovals).toEqual([{ versionId: V120, fileId: config.id }]),
    );
  });
});

/**
 * The highlighter's chunk as a page's first file meets it: each test imports SourceFiles afresh,
 * so its lazy import starts unloaded, and may stand in for the chunk.
 */
describe("SourceFiles and the highlighter's chunk", () => {
  const CHUNK = "./source/SourceView";
  const released = aVersion({ status: "released", files: [sketch] });

  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.doUnmock(CHUNK);
  });

  async function freshSourceFiles() {
    return (await import("./SourceFiles")).SourceFiles;
  }

  it("shows the text plain at once, then highlighted and numbered", async () => {
    const Fresh = await freshSourceFiles();
    renderWithProviders(<Fresh version={released} framework="arduino" />);

    const box = screen.getByRole("group", { name: "weather_station.ino" });
    expect(codeOf(box)).toBe(sketch.content);
    expect(within(box).queryByText('"config.h"')).not.toBeInTheDocument();

    // The highlighted box takes the plain one's place.
    expect(await screen.findByText('"config.h"')).toHaveClass("tok-string");
    const highlighted = screen.getByRole("group", { name: "weather_station.ino" });
    expect(codeOf(highlighted)).toBe(sketch.content);
    const numbers = highlighted.querySelectorAll('[aria-hidden="true"]');
    expect([...numbers].map((number) => number.textContent)).toEqual(["1", "2", "3", "4", "5"]);
  });

  it("never asks for the highlighter when no file has text to highlight", async () => {
    const asked = vi.fn();
    vi.doMock(CHUNK, async (importOriginal) => {
      asked();
      return importOriginal();
    });
    const Fresh = await freshSourceFiles();
    const empty = aSourceFile({ path: "main.py", content: "" });
    const table = aSourceFile({ path: "table.h", content: "0x00,\n".repeat(5_001) });
    renderWithProviders(
      <Fresh version={aVersion({ files: [empty, table] })} framework="micropython" />,
    );

    expect(screen.getByRole("group", { name: "table.h" })).toBeVisible();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(asked).not.toHaveBeenCalled();
  });

  it("keeps the plain text when the highlighter can't load, saying so", async () => {
    vi.doMock(CHUNK, () => {
      throw new Error("The chunk is gone after a deploy.");
    });
    // React reports the error the boundary catches; it is the one this test causes.
    const reported = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      const Fresh = await freshSourceFiles();
      renderWithProviders(<Fresh version={released} framework="arduino" />);

      const failed = "Highlighting couldn't load, so this file is shown as plain text.";
      expect(await screen.findByText(failed)).toBeVisible();
      const box = screen.getByRole("group", { name: "weather_station.ino" });
      expect(box).toHaveAccessibleDescription(failed);
      expect(codeOf(box)).toBe(sketch.content);
      expect(box.textContent).toBe(sketch.content);
    } finally {
      reported.mockRestore();
    }
  });
});
