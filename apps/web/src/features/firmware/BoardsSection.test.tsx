import { screen, within } from "@testing-library/react";
import type { RunsOn } from "@wiredex/api-client";
import { describe, expect, it } from "vitest";
import { FIRMWARE_ID, V100, V110, v100, v110, v120, weatherStationWith } from "../../test/firmware";
import { renderInRouter } from "../../test/render";
import { aBoard, aFlash, respondWithBoards } from "../../test/server";
import { BoardsSection } from "./BoardsSection";

const station = weatherStationWith([v120, v110, v100]);

const greenhouseA: RunsOn = {
  revision_id: "0199eeee-0000-7000-8000-000000000003",
  project_id: "0199eeee-0000-7000-8000-000000000001",
  project_name: "Greenhouse controller",
  label: "A",
  summary: null,
};

const esp32 = { id: "0199dddd-0000-7000-8000-0000000000c1", code: "WX-U-0001" };
const pico = { id: "0199dddd-0000-7000-8000-0000000000c2", code: "WX-U-0002" };

describe("BoardsSection", () => {
  it("lists each board with its version, when it was flashed, where it is now and a newer release", async () => {
    respondWithBoards(FIRMWARE_ID, [
      aBoard({
        unit: esp32,
        revision: greenhouseA,
        flash: aFlash({
          id: "0199ffff-0000-7000-8000-0000000000d1",
          unit: esp32,
          version: { id: V110, version: "1.1.0" },
          flashed_at: "2026-09-29T12:00:00Z",
        }),
      }),
      aBoard({
        unit: pico,
        flash: aFlash({ unit: pico, version: { id: V100, version: "1.0.0" } }),
        newer_release: { id: V110, version: "1.1.0" },
      }),
    ]);
    renderInRouter(<BoardsSection firmware={station} />);

    const section = await screen.findByRole("region", { name: "Boards" });
    const table = await within(section).findByRole("table", {
      name: "Boards running Weather station, by code",
    });
    const rows = within(table).getAllByRole("row");
    const esp32Row = within(rows[1] as HTMLElement);
    const picoRow = within(rows[2] as HTMLElement);

    expect(esp32Row.getByRole("link", { name: "WX-U-0001" })).toHaveAttribute(
      "href",
      `/units/${esp32.id}`,
    );
    expect(esp32Row.getByRole("link", { name: "1.1.0" })).toHaveAttribute(
      "href",
      `/firmware/${FIRMWARE_ID}/versions/${V110}`,
    );
    expect(esp32Row.getByRole("link", { name: "Greenhouse controller · A" })).toHaveAttribute(
      "href",
      `/projects/${greenhouseA.project_id}/revisions/${greenhouseA.revision_id}`,
    );
    expect(esp32Row.getByText(/2026/)).toHaveAttribute("datetime", "2026-09-29T12:00:00Z");
    expect(esp32Row.queryByText(/is out/)).not.toBeInTheDocument();

    // A board on an older version says so in words, beside its icon, and links the release.
    expect(picoRow.getByRole("link", { name: "1.0.0" })).toBeInTheDocument();
    expect(picoRow.getByRole("link", { name: "1.1.0 is out" })).toHaveAttribute(
      "href",
      `/firmware/${FIRMWARE_ID}/versions/${V110}`,
    );
    expect(picoRow.getByText("Not in a build")).toBeInTheDocument();
  });

  it("is a block whose table can reflow, each cell but the board's code labelled", async () => {
    respondWithBoards(FIRMWARE_ID, [
      aBoard({
        unit: esp32,
        flash: aFlash({ unit: esp32, version: { id: V110, version: "1.1.0" } }),
      }),
    ]);
    renderInRouter(<BoardsSection firmware={station} span="xl-row" />);

    const section = await screen.findByRole("region", { name: "Boards" });
    expect(within(section).getByRole("heading", { level: 2 })).toHaveTextContent("Boards");
    expect(section).toHaveClass("xl:col-span-2", "2xl:col-span-1");
    const table = await within(section).findByRole("table");
    expect(table.parentElement).toHaveAttribute("data-stack", "xs");
    const row = within(table).getAllByRole("row")[1] as HTMLElement;
    expect(within(row).getByRole("rowheader")).not.toHaveAttribute("data-label");
    expect(
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.getAttribute("data-label")),
    ).toEqual(["Version", "Flashed", "Where it is now"]);
  });

  it("says so when no board runs the firmware", async () => {
    respondWithBoards(FIRMWARE_ID, []);
    renderInRouter(<BoardsSection firmware={station} />);

    const section = await screen.findByRole("region", { name: "Boards" });
    expect(
      await within(section).findByText("No board runs this firmware yet."),
    ).toBeInTheDocument();
    expect(within(section).queryByRole("table")).not.toBeInTheDocument();
  });

  it("says so when the boards can't be loaded", async () => {
    respondWithBoards("0199ffff-0000-7000-8000-0000000000ff", []);
    renderInRouter(<BoardsSection firmware={station} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The boards couldn't be loaded.");
  });
});
