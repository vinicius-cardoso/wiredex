import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { config, sketch, V120, weatherStationWith } from "../../test/firmware";
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
    expect(first.querySelector("pre")?.textContent).toBe(sketch.content);
    const second = within(files).getByRole("region", { name: "config.h" });
    expect(second).toHaveAttribute("id", `file-${config.id}`);
    expect(second).toHaveTextContent(`${config.size} B · 2 lines`);
    expect(second.querySelector("pre")?.textContent).toBe(config.content);
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
    expect(screen.getByRole("region", { name: "main.py" })).toHaveTextContent("0 B · empty");
  });

  it("says so when the version has no file yet", () => {
    renderWithProviders(<SourceFiles version={aVersion()} framework="arduino" />);
    expect(screen.getByRole("region", { name: "Source files" })).toHaveTextContent(
      "No source files yet.",
    );
  });

  it("shows a draft against its limits, and asks in place before removing a file", async () => {
    const user = userEvent.setup();
    const draft = aVersion({ id: V120, version: "1.2.0", files: [sketch, config] });
    const writes = acceptFirmwareWrites([weatherStationWith([draft])], { versions: [draft] });
    renderWithProviders(<SourceFiles version={draft} framework="arduino" />);
    const files = screen.getByRole("region", { name: "Source files" });
    expect(files).toHaveTextContent(`${sketch.size + config.size} B of 1.0 MB · 2 of 100 files`);
    expect(within(files).getByRole("button", { name: "Edit weather_station.ino" })).toBeVisible();

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
