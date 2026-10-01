import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { FIRMWARE_ID, V100, V110, v100, v110, v120, weatherStationWith } from "../../test/firmware";
import { renderInRouter } from "../../test/render";
import {
  acceptFlashWrites,
  aFlash,
  aUnit,
  aUnitFirmware,
  respondWithUnitFirmware,
} from "../../test/server";
import { FlashLogSection } from "./FlashLogSection";

const board = aUnit();
const station = weatherStationWith([v120, v110, v100]);

const greenhouseA = {
  revision_id: "0199eeee-0000-7000-8000-000000000003",
  project_id: "0199eeee-0000-7000-8000-000000000001",
  project_name: "Greenhouse controller",
  label: "A",
  summary: null,
};

const older = aFlash({
  id: "0199ffff-0000-7000-8000-0000000000d1",
  version: { id: V100, version: "1.0.0" },
  flashed_at: "2026-09-28T10:30:00Z",
  notes: "Checking a new board",
});

const newer = aFlash({
  id: "0199ffff-0000-7000-8000-0000000000d2",
  version: { id: V110, version: "1.1.0" },
  revision: greenhouseA,
  flashed_at: "2026-09-29T10:30:00Z",
  created_at: "2026-09-29T10:31:00Z",
});

function renderSection(unit = board) {
  renderInRouter(<FlashLogSection unit={unit} />);
  return screen.findByRole("region", { name: "Firmware" });
}

describe("FlashLogSection", () => {
  it("shows the current version, a newer release in words, and the log", async () => {
    respondWithUnitFirmware(
      aUnitFirmware({
        current: older,
        newer_release: { id: V110, version: "1.1.0" },
        flashes: [older],
      }),
    );
    const section = await renderSection();

    expect(await within(section).findByRole("link", { name: "1.1.0 is out" })).toHaveAttribute(
      "href",
      `/firmware/${FIRMWARE_ID}/versions/${V110}`,
    );
    const links = within(section).getAllByRole("link", { name: "Weather station" });
    expect(links[0]).toHaveAttribute("href", `/firmware/${FIRMWARE_ID}`);
    const table = within(section).getByRole("table", {
      name: "Flash log of WX-U-0001, newest first",
    });
    const [, row] = within(table).getAllByRole("row");
    expect(row).toHaveTextContent("Checking a new board");
    expect(within(row as HTMLElement).getByRole("link", { name: "1.0.0" })).toHaveAttribute(
      "href",
      `/firmware/${FIRMWARE_ID}/versions/${V100}`,
    );
    expect(section.querySelector(`time[datetime="${older.flashed_at}"]`)).not.toBeNull();
    expect(within(section).getByRole("button", { name: "Log a flash" })).toBeInTheDocument();
  });

  it("says when no flash is logged, with no log to show", async () => {
    respondWithUnitFirmware(aUnitFirmware());
    const section = await renderSection();

    expect(
      await within(section).findByText("No flash is logged on this board yet."),
    ).toBeInTheDocument();
    expect(within(section).queryByRole("table")).not.toBeInTheDocument();
    expect(within(section).queryByText(/is out/)).not.toBeInTheDocument();
  });

  it("asks in its row before removing an entry, and the one before becomes current", async () => {
    const writes = acceptFlashWrites(aUnitFirmware({ flashes: [newer, older] }), {
      firmware: [station],
    });
    const section = await renderSection();
    const user = userEvent.setup();

    const table = await within(section).findByRole("table");
    expect(within(section).queryByText(/is out/)).not.toBeInTheDocument();
    expect(within(table).getByRole("link", { name: "Greenhouse controller · A" })).toHaveAttribute(
      "href",
      `/projects/${greenhouseA.project_id}/revisions/${greenhouseA.revision_id}`,
    );
    await user.click(
      within(table).getByRole("button", { name: /^Remove the flash of Weather station 1\.1\.0/ }),
    );
    const [, first] = within(table).getAllByRole("row");
    expect(first).toHaveTextContent("Remove this entry from the log?");
    expect(within(first as HTMLElement).getByRole("button", { name: "Keep it" })).toHaveFocus();
    expect(writes.removals).toEqual([]);
    await user.click(within(first as HTMLElement).getByRole("button", { name: "Yes, remove it" }));

    expect(await within(section).findByRole("link", { name: "1.1.0 is out" })).toBeInTheDocument();
    expect(writes.removals).toEqual([newer.id]);
    expect(within(table).getAllByRole("row")).toHaveLength(2);
  });

  it("keeps an entry when the question is answered no", async () => {
    const writes = acceptFlashWrites(aUnitFirmware({ flashes: [older] }), { firmware: [station] });
    const section = await renderSection();
    const user = userEvent.setup();

    const remove = await within(section).findByRole("button", { name: /^Remove the flash of/ });
    await user.click(remove);
    await user.click(within(section).getByRole("button", { name: "Keep it" }));

    expect(within(section).getByRole("button", { name: /^Remove the flash of/ })).toHaveFocus();
    expect(writes.removals).toEqual([]);
  });

  it("shows a retired unit's log without Log a flash, saying why", async () => {
    const retired = aUnit({ status: "retired", location: null });
    respondWithUnitFirmware(aUnitFirmware({ retired: true, current: older, flashes: [older] }));
    const section = await renderSection(retired);

    expect(await within(section).findByRole("table")).toBeInTheDocument();
    expect(
      within(section).getByText(
        "This unit is retired, so no flash can be logged on it. Un-retire it first.",
      ),
    ).toBeInTheDocument();
    expect(within(section).queryByRole("button", { name: "Log a flash" })).not.toBeInTheDocument();
  });
});
