import { screen, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { codeOf, config, openFile, sketch, V120 } from "../../../test/firmware";
import { renderWithProviders } from "../../../test/render";
import { aVersion } from "../../../test/server";
import { SourceFiles } from "../SourceFiles";

const released = aVersion({ status: "released", files: [sketch, config] });

/** The opened file's region once its text is highlighted and numbered. */
async function highlighted(user: UserEvent, path: string): Promise<HTMLElement> {
  await openFile(user, path);
  await screen.findByText('"config.h"');
  return screen.getByRole("region", { name: path });
}

/** What the page has selected, less the line numbers a browser leaves out as unselectable. */
function selectedCode(): string {
  const selection = document.getSelection();
  const selected = document.createElement("div");
  if (selection?.rangeCount) selected.append(selection.getRangeAt(0).cloneContents());
  return codeOf(selected);
}

describe("CopyButton", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.getSelection()?.removeAllRanges();
  });

  it("puts exactly the stored text on the clipboard, and says which file it copied", async () => {
    // user-event stands a clipboard in for the browser's, which reads back what was written.
    const user = userEvent.setup();
    renderWithProviders(<SourceFiles version={released} framework="arduino" />);
    const first = await highlighted(user, "weather_station.ino");

    await user.click(within(first).getByRole("button", { name: "Copy weather_station.ino" }));
    // The tab, the trailing spaces and the final break, without a number or a CR.
    const copied = await navigator.clipboard.readText();
    expect(copied).toBe(sketch.content);
    expect(copied).not.toContain("\r");
    expect(within(first).getByRole("status")).toHaveTextContent("Copied weather_station.ino.");

    // Wrapping changes how the text looks, not what is copied.
    await user.click(screen.getByRole("switch", { name: "Wrap long lines" }));
    await openFile(user, "config.h");
    const second = screen.getByRole("region", { name: "config.h" });
    await user.click(within(second).getByRole("button", { name: "Copy config.h" }));
    expect(await navigator.clipboard.readText()).toBe(config.content);
    expect(within(second).getByRole("status")).toHaveTextContent("Copied config.h.");
  });

  it.each([
    [
      "refuses",
      () => {
        vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(
          new DOMException("Write permission denied.", "NotAllowedError"),
        );
      },
    ],
    [
      "is missing, outside a secure context",
      () => {
        Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
      },
    ],
  ])("selects the text and says how to copy it when the clipboard %s", async (_, takeAway) => {
    // After user-event stands its clipboard in, so the test takes that one away.
    const user = userEvent.setup();
    takeAway();
    renderWithProviders(<SourceFiles version={released} framework="arduino" />);
    const first = await highlighted(user, "weather_station.ino");

    await user.click(within(first).getByRole("button", { name: "Copy weather_station.ino" }));
    expect(within(first).getByRole("status")).toHaveTextContent(
      "The clipboard can't be written here, so weather_station.ino is selected instead. Press Ctrl+C, or ⌘C on a Mac, to copy it.",
    );
    // The file's own box is selected, all of its text and nothing else.
    const box = within(first).getByRole("group", { name: "weather_station.ino" });
    expect(box.contains(document.getSelection()?.anchorNode ?? null)).toBe(true);
    expect(selectedCode()).toBe(sketch.content);
  });

  it("offers Copy on a draft's files, before Edit and Remove, as on a release's", async () => {
    const user = userEvent.setup();
    const draft = aVersion({ id: V120, version: "1.2.0", files: [sketch] });
    const { unmount } = renderWithProviders(<SourceFiles version={draft} framework="arduino" />);
    await openFile(user, "weather_station.ino");
    const drafted = screen.getByRole("region", { name: "weather_station.ino" });
    expect(within(drafted).getAllByRole("button")).toEqual([
      within(drafted).getByRole("button", { name: "Copy weather_station.ino" }),
      within(drafted).getByRole("button", { name: "Edit weather_station.ino" }),
      within(drafted).getByRole("button", { name: "Remove weather_station.ino" }),
    ]);
    unmount();

    renderWithProviders(<SourceFiles version={released} framework="arduino" />);
    const release = screen.getByRole("region", { name: "weather_station.ino" });
    expect(within(release).getAllByRole("button")).toEqual([
      within(release).getByRole("button", { name: "Copy weather_station.ino" }),
    ]);
  });
});
