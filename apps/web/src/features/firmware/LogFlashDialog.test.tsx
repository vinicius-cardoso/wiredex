import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { RunsOn } from "@wiredex/api-client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  FIRMWARE_ID,
  renderFirmwareAt,
  V100,
  V110,
  V120,
  v100,
  v110,
  v120,
  weatherStationWith,
} from "../../test/firmware";
import { renderInRouter } from "../../test/render";
import {
  aBoard,
  acceptFirmwareWrites,
  acceptFlashWrites,
  aFirmware,
  aUnit,
  aUnitFirmware,
  NEW_FLASH_IDS,
  respondWithBoards,
  respondWithUnitSearch,
} from "../../test/server";
import { CurrentFirmware, FlashLog } from "./FlashLogSection";

const greenhouseA: RunsOn = {
  revision_id: "0199eeee-0000-7000-8000-000000000003",
  project_id: "0199eeee-0000-7000-8000-000000000001",
  project_name: "Greenhouse controller",
  label: "A",
  summary: null,
};

const station = weatherStationWith([v120, v110, v100]);
const greenhouse = aFirmware({
  id: "0199ffff-0000-7000-8000-000000000002",
  name: "Greenhouse controller",
  runs_on: [greenhouseA],
});
const blink = aFirmware({ id: "0199ffff-0000-7000-8000-000000000003", name: "Blink" });

const reserved = aUnit({
  status: "reserved",
  revision_id: greenhouseA.revision_id,
  location: null,
});

/** The blocks on a unit's page, its log taking writes, with the workspace's firmware. */
async function openDialog(unit = reserved) {
  acceptFirmwareWrites([station, greenhouse, blink], {
    revisions: [greenhouseA],
    versions: [v120, v110, v100],
  });
  const writes = acceptFlashWrites(aUnitFirmware(), {
    firmware: [station, greenhouse, blink],
    revision: unit.revision_id ? greenhouseA : null,
  });
  renderInRouter(
    <>
      <CurrentFirmware unit={unit} />
      <FlashLog unit={unit} />
    </>,
  );
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Log a flash" }));
  const dialog = screen.getByRole("dialog", { name: "Log a flash on WX-U-0001" });
  return { writes, user, dialog };
}

describe("LogFlashDialog", () => {
  beforeEach(() => {
    // Only the clock is fixed: MSW and the user's events keep their timers.
    vi.useFakeTimers({ now: new Date(2026, 9, 1, 14, 30, 20), toFake: ["Date"] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("lists the firmware on the unit's revision first, and released versions only", async () => {
    const { user, dialog } = await openDialog();

    const firmware = await within(dialog).findByRole("combobox", { name: "Firmware" });
    const groups = within(firmware).getAllByRole("group");
    expect(groups.map((group) => group.getAttribute("label"))).toEqual([
      "Running on its revision",
      "Other firmware",
    ]);
    const names = (group: HTMLElement) =>
      within(group)
        .getAllByRole("option")
        .map((option) => option.textContent);
    expect(names(groups[0] as HTMLElement)).toEqual(["Greenhouse controller"]);
    expect(names(groups[1] as HTMLElement)).toEqual(["Blink", "Weather station"]);
    expect(
      await within(dialog).findByText(
        "Greenhouse controller has no released version yet. Release one to log a flash of it.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Log flash" })).toBeDisabled();

    await user.selectOptions(firmware, "Weather station");
    const version = await within(dialog).findByRole("combobox", { name: "Version" });
    expect(
      within(version)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["1.1.0", "1.0.0"]);
    expect(version).toHaveValue(V110);
  });

  it("offers the firmware by name alone for a unit no revision holds", async () => {
    const { dialog } = await openDialog(aUnit());

    const firmware = await within(dialog).findByRole("combobox", { name: "Firmware" });
    expect(within(firmware).queryByRole("group")).not.toBeInTheDocument();
    expect(
      within(firmware)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Blink", "Greenhouse controller", "Weather station"]);
  });

  it("logs the flash as now when the time is left as it opened", async () => {
    const { writes, user, dialog } = await openDialog();

    await user.selectOptions(
      await within(dialog).findByRole("combobox", { name: "Firmware" }),
      "Weather station",
    );
    await user.selectOptions(
      await within(dialog).findByRole("combobox", { name: "Version" }),
      "1.0.0",
    );
    expect(within(dialog).getByLabelText("Flashed at")).toHaveValue("2026-10-01T14:30");
    await user.type(within(dialog).getByRole("textbox", { name: "Notes" }), "  Bench   test ");
    await user.click(within(dialog).getByRole("button", { name: "Log flash" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(writes.logged).toEqual([
      {
        unitId: reserved.id,
        body: { version_id: V100, flashed_at: null, notes: "Bench test" },
      },
    ]);
    const section = screen.getByRole("region", { name: "Firmware" });
    expect(await within(section).findByRole("link", { name: "1.1.0 is out" })).toBeInTheDocument();
    const log = screen.getByRole("region", { name: "Flash log" });
    expect(
      within(log).getByRole("link", { name: "Greenhouse controller · A" }),
    ).toBeInTheDocument();
    expect(writes.log().current?.id).toBe(NEW_FLASH_IDS[0]);
  });

  it("marks a time more than five minutes ahead, and sends a chosen one with its offset", async () => {
    const { writes, user, dialog } = await openDialog();

    await user.selectOptions(
      await within(dialog).findByRole("combobox", { name: "Firmware" }),
      "Weather station",
    );
    await within(dialog).findByRole("combobox", { name: "Version" });
    const time = within(dialog).getByLabelText("Flashed at");
    fireEvent.change(time, { target: { value: "2026-10-01T14:40" } });
    await user.click(within(dialog).getByRole("button", { name: "Log flash" }));

    expect(time).toHaveAttribute("aria-invalid", "true");
    expect(time).toHaveAccessibleDescription(
      expect.stringContaining("A flash can't be dated more than five minutes from now."),
    );
    expect(writes.logged).toEqual([]);

    fireEvent.change(time, { target: { value: "2026-09-30T09:15" } });
    await user.click(within(dialog).getByRole("button", { name: "Log flash" }));

    await waitFor(() => expect(writes.logged).toHaveLength(1));
    const sent = writes.logged[0]?.body.flashed_at ?? "";
    expect(sent).toMatch(/^2026-09-30T09:15:00[+-]\d{2}:\d{2}$/);
    expect(Date.parse(sent)).toBe(new Date(2026, 8, 30, 9, 15).getTime());
  });

  it("logs a flash from a released version, on the board the picker finds", async () => {
    const pico = aUnit({
      id: "0199dddd-0000-7000-8000-0000000000c2",
      code: "WX-U-0002",
      mac: "aa:bb:cc:00:11:33",
    });
    const broken = aUnit({
      id: "0199dddd-0000-7000-8000-0000000000c3",
      code: "WX-U-0003",
      status: "retired",
    });
    acceptFirmwareWrites([station], { versions: [v120, v110, v100] });
    respondWithUnitSearch([pico, broken]);
    const writes = acceptFlashWrites(aUnitFirmware({ unit: { id: pico.id, code: pico.code } }), {
      firmware: [station],
    });
    // The firmware's boards, from the log as it stands, so a flash shows there in place.
    respondWithBoards(FIRMWARE_ID, () => {
      const current = writes.log().current;
      return current ? [aBoard({ flash: current })] : [];
    });
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}/versions/${V110}`);
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Version 1.1.0" });
    const boards = screen.getByRole("region", { name: "Boards" });
    expect(await within(boards).findByText("No board runs this firmware yet.")).toBeInTheDocument();
    // First among a release's actions, right above the files it copies.
    await within(panel).findByRole("button", { name: "New version from this" });
    expect(within(panel).getAllByRole("button")[0]).toHaveAccessibleName("Log a flash");
    await user.click(within(panel).getByRole("button", { name: "Log a flash" }));
    const dialog = screen.getByRole("dialog", { name: "Log a flash of Weather station 1.1.0" });

    // Logged before a board is chosen, it asks for one and sends nothing.
    await user.click(within(dialog).getByRole("button", { name: "Log flash" }));
    const board = within(dialog).getByRole("combobox", { name: "Board" });
    expect(board).toHaveAttribute("aria-invalid", "true");
    expect(board).toHaveAccessibleDescription("Choose the board that was flashed.");
    expect(writes.logged).toEqual([]);

    await user.type(board, "WX-U");
    expect(await within(dialog).findByRole("option", { name: /WX-U-0003/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await user.click(within(dialog).getByRole("option", { name: /WX-U-0002/ }));
    expect(board).toHaveValue("WX-U-0002");
    expect(board).not.toHaveAttribute("aria-invalid");
    await user.click(within(dialog).getByRole("button", { name: "Log flash" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(writes.logged).toEqual([
      { unitId: pico.id, body: { version_id: V110, flashed_at: null, notes: null } },
    ]);
    expect(await within(boards).findByRole("link", { name: "WX-U-0002" })).toHaveAttribute(
      "href",
      `/units/${pico.id}`,
    );
  });

  it("offers no flash on a draft", async () => {
    acceptFirmwareWrites([station], { versions: [v120, v110, v100] });
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}/versions/${V120}`);

    const panel = await screen.findByRole("region", { name: "Version 1.2.0" });
    expect(await within(panel).findByRole("button", { name: "Edit version" })).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Log a flash" })).not.toBeInTheDocument();
  });
});
