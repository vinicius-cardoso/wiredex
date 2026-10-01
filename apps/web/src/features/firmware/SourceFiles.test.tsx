import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { config, sketch } from "../../test/firmware";
import { renderWithProviders } from "../../test/render";
import { aSourceFile, aVersion } from "../../test/server";
import { SourceFiles } from "./SourceFiles";

describe("SourceFiles", () => {
  it("shows each file's text as stored, under its path with its size and line count", () => {
    renderWithProviders(<SourceFiles version={aVersion({ files: [sketch, config] })} />);

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
  });

  it("lists no index for a single file, and counts an empty one as empty", () => {
    const empty = aSourceFile({ path: "main.py", content: "" });
    renderWithProviders(<SourceFiles version={aVersion({ files: [empty] })} />);

    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "main.py" })).toHaveTextContent("0 B · empty");
  });

  it("says so when the version has no file yet", () => {
    renderWithProviders(<SourceFiles version={aVersion()} />);

    expect(screen.getByRole("region", { name: "Source files" })).toHaveTextContent(
      "No source files yet.",
    );
  });
});
