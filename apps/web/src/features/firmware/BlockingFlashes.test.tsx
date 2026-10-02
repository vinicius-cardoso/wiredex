import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { BlockingFlash } from "@wiredex/api-client";
import { describe, expect, it } from "vitest";
import {
  FIRMWARE_ID,
  renderFirmwareAt,
  V100,
  V110,
  v100,
  v110,
  v120,
  weatherStationWith,
} from "../../test/firmware";
import { acceptFirmwareWrites } from "../../test/server";

const station = weatherStationWith([v120, v110, v100]);
const versions = [v120, v110, v100];

/** The Pico, still in inventory, flashed with 1.0.0. */
const onPico: BlockingFlash = {
  id: "0199ffff-0000-7000-8000-0000000000d1",
  unit: { id: "0199dddd-0000-7000-8000-0000000000c2", code: "WX-U-0002" },
  unit_present: true,
  version: { id: V100, version: "1.0.0" },
  flashed_at: "2026-09-28T10:30:00Z",
};

/** A board deleted from inventory since it was flashed with 1.0.0: its page is gone. */
const onDeleted: BlockingFlash = {
  id: "0199ffff-0000-7000-8000-0000000000d2",
  unit: { id: "0199dddd-0000-7000-8000-0000000000c3", code: "WX-U-0003" },
  unit_present: false,
  version: { id: V100, version: "1.0.0" },
  flashed_at: "2026-09-20T08:00:00Z",
};

/** The ESP32, flashed with 1.1.0. */
const onEsp32: BlockingFlash = {
  id: "0199ffff-0000-7000-8000-0000000000d3",
  unit: { id: "0199dddd-0000-7000-8000-0000000000c1", code: "WX-U-0001" },
  unit_present: true,
  version: { id: V110, version: "1.1.0" },
  flashed_at: "2026-09-29T12:00:00Z",
};

describe("BlockingFlashes", () => {
  it("lists the flashes that keep a version, and removes each there until it can go", async () => {
    const writes = acceptFirmwareWrites([station], {
      versions,
      flashed: [onPico, onDeleted],
    });
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}/versions/${V100}`);
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Version 1.0.0" });
    await user.click(await within(panel).findByRole("button", { name: "Delete version" }));
    const question = within(panel).getByRole("group", {
      name: "Delete version 1.0.0 with its source files?",
    });
    await user.click(within(question).getByRole("button", { name: "Yes, delete it" }));

    expect(await within(question).findByRole("alert")).toHaveTextContent(
      "1.0.0 is in a board's flash log: remove those entries to delete it.",
    );
    const entries = within(question).getByRole("list", { name: "Flash log entries in the way" });
    const [pico, deleted] = within(entries).getAllByRole("listitem") as [HTMLElement, HTMLElement];
    // A unit inventory still holds links to its page; a deleted one says it is gone instead.
    expect(within(pico).getByRole("link", { name: "WX-U-0002" })).toHaveAttribute(
      "href",
      `/units/${onPico.unit.id}`,
    );
    expect(pico).toHaveTextContent("1.0.0, flashed");
    expect(within(deleted).queryByRole("link")).not.toBeInTheDocument();
    expect(deleted).toHaveTextContent("WX-U-0003 (no longer in inventory)");

    // Removing asks in the entry's row first.
    await user.click(
      within(deleted).getByRole("button", { name: /^Remove the flash of 1\.0\.0 on WX-U-0003/ }),
    );
    expect(within(deleted).getByText("Remove this entry from the log?")).toBeInTheDocument();
    await user.click(within(deleted).getByRole("button", { name: "Yes, remove it" }));

    await waitFor(() => expect(within(entries).getAllByRole("listitem")).toHaveLength(1));
    expect(writes.flashRemovals).toEqual([onDeleted.id]);

    await user.click(within(entries).getByRole("button", { name: /^Remove the flash of 1\.0\.0/ }));
    await user.click(within(entries).getByRole("button", { name: "Yes, remove it" }));

    expect(await within(question).findByRole("status")).toHaveTextContent(
      "Those entries are removed: delete it again to finish.",
    );
    expect(within(question).queryByRole("list")).not.toBeInTheDocument();
    expect(writes.flashRemovals).toEqual([onDeleted.id, onPico.id]);

    await user.click(within(question).getByRole("button", { name: "Yes, delete it" }));

    expect(await screen.findByRole("region", { name: "Version 1.2.0" })).toBeInTheDocument();
    expect(writes.versionDeletions).toEqual([V100, V100]);
  });

  it("lists the flashes that keep a firmware under its refused delete, each with its version", async () => {
    const writes = acceptFirmwareWrites([station], { versions, flashed: [onPico, onEsp32] });
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}`);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Move to trash" }));
    const question = screen.getByRole("group", {
      name: "Move Weather station with all its versions and source files to the trash? You can restore it from there.",
    });
    await user.click(within(question).getByRole("button", { name: "Yes, move it" }));

    expect(await within(question).findByRole("alert")).toHaveTextContent(
      "A version of Weather station is in a board's flash log: remove those entries to move it to the trash.",
    );
    const entries = within(question).getByRole("list", { name: "Flash log entries in the way" });
    const items = within(entries).getAllByRole("listitem");
    expect(items.map((item) => within(item).getByRole("link").textContent)).toEqual([
      "WX-U-0002",
      "WX-U-0001",
    ]);
    expect(items[1]).toHaveTextContent("1.1.0, flashed");
    expect(writes.deletions).toEqual([FIRMWARE_ID]);
    expect(writes.firmware()).toHaveLength(1);

    // Keeping the firmware forgets the refusal: the next question starts afresh.
    await user.click(within(question).getByRole("button", { name: "Keep it" }));
    await user.click(screen.getByRole("button", { name: "Move to trash" }));
    expect(screen.queryByRole("list", { name: "Flash log entries in the way" })).toBeNull();
  });
});
