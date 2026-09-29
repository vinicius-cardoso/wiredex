import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderInRouter } from "../../../test/render";
import { acceptNetWrites, aNet, aNetlist, aRevision } from "../../../test/server";
import { NetlistSection } from "./NetlistSection";

const REVISION = aRevision();

const picked = aNetlist({
  nets: [aNet()],
  designators: [
    { designator: "U1", part_id: "esp", part_name: "ESP32-DevKitC" },
    { designator: "U2", part_id: "bme", part_name: "BME280" },
  ],
  parts: [
    {
      part_id: "esp",
      name: "ESP32-DevKitC",
      has_pinout: true,
      pins: [
        { number: "14", label: "GND", type: "ground", functions: [], voltage: null },
        { number: "25", label: "GPIO21", type: "io", functions: ["SDA"], voltage: "3.3" },
      ],
    },
  ],
});

async function renderEditor(refuse: Parameters<typeof acceptNetWrites>[2] = null) {
  const writes = acceptNetWrites(REVISION.id, picked, refuse);
  renderInRouter(<NetlistSection revision={REVISION} />);
  const section = await screen.findByRole("region", { name: "Wiring" });
  const row = await within(section).findByRole("row", { name: "New net" });
  return { writes, section, row, user: userEvent.setup() };
}

describe("the netlist editor", () => {
  it("adds a net from the keyboard and clears for the next one", async () => {
    const { writes, row, user } = await renderEditor();

    await user.type(within(row).getByRole("textbox", { name: "Net name" }), "SCL");
    await user.selectOptions(within(row).getByRole("combobox", { name: "Wire color" }), "yellow");
    await user.type(within(row).getByRole("combobox", { name: "Pins" }), "U1.22, R2.2");
    await user.type(within(row).getByRole("textbox", { name: "Notes" }), "pull-up{Enter}");

    expect(writes.additions).toEqual([
      { name: "SCL", color: "yellow", pins: "U1.22, R2.2", notes: "pull-up" },
    ]);
    expect(await screen.findByRole("row", { name: /^SCL/ })).toBeInTheDocument();
    expect(within(row).getByRole("textbox", { name: "Net name" })).toHaveValue("");
    expect(within(row).getByRole("textbox", { name: "Net name" })).toHaveFocus();
  });

  it("offers designators, then a part's pins, picked with the arrows and Enter", async () => {
    const { row, user } = await renderEditor();
    const pins = within(row).getByRole("combobox", { name: "Pins" });

    await user.type(pins, "u");
    expect(within(row).getByRole("option", { name: /U1/ })).toBeInTheDocument();
    await user.keyboard("{ArrowDown}{Enter}");
    expect(pins).toHaveValue("U1.");

    await user.type(pins, "sd");
    expect(within(row).getByRole("option", { name: /25.*GPIO21/ })).toBeInTheDocument();
    await user.keyboard("{ArrowDown}{Enter}");
    expect(pins).toHaveValue("U1.25");
    expect(pins).toHaveAttribute("aria-expanded", "false");
  });

  it("shows a refused pin on its field, naming the reference and its candidates", async () => {
    const { row, user } = await renderEditor({
      status: 422,
      body: { code: "ambiguous_pin", field: "pins", item: "U1.GND", candidates: ["14", "20"] },
    });

    await user.type(within(row).getByRole("textbox", { name: "Net name" }), "GND");
    await user.type(within(row).getByRole("combobox", { name: "Pins" }), "U1.GND{Escape}{Enter}");

    expect(
      await within(row).findByText("U1.GND could be pins 14, 20; name one by number."),
    ).toBeInTheDocument();
    expect(within(row).getByRole("combobox", { name: "Pins" })).toHaveFocus();
  });

  it("edits a net in its row, and Escape puts it back", async () => {
    const { writes, section, user } = await renderEditor();

    await user.click(within(section).getByRole("button", { name: "Edit net SDA" }));
    const editing = within(section).getByRole("row", { name: "Editing net SDA" });
    const name = within(editing).getByRole("textbox", { name: "Net name" });
    await user.clear(name);
    await user.type(name, "I2C_SDA{Escape}");
    expect(within(section).getByRole("button", { name: "Edit net SDA" })).toHaveFocus();

    await user.click(within(section).getByRole("button", { name: "Edit net SDA" }));
    const again = within(section).getByRole("row", { name: "Editing net SDA" });
    await user.selectOptions(within(again).getByRole("combobox", { name: "Wire color" }), "green");
    await user.type(within(again).getByRole("textbox", { name: "Net name" }), "{Enter}");

    expect(writes.edits).toEqual([
      { netId: aNet().id, body: { name: "SDA", color: "green", pins: "U1.25", notes: null } },
    ]);
  });

  it("asks before removing a net, focus on Keep", async () => {
    const { writes, section, user } = await renderEditor();

    await user.click(within(section).getByRole("button", { name: "Remove net SDA" }));
    expect(within(section).getByRole("button", { name: "Keep" })).toHaveFocus();
    await user.click(within(section).getByRole("button", { name: "Remove" }));

    expect(writes.removals).toEqual([aNet().id]);
  });

  it("offers the new-net row on an empty draft", async () => {
    acceptNetWrites(REVISION.id, aNetlist({ ...picked, nets: [] }));
    renderInRouter(<NetlistSection revision={REVISION} />);
    const section = await screen.findByRole("region", { name: "Wiring" });

    expect(await within(section).findByRole("row", { name: "New net" })).toBeInTheDocument();
    expect(within(section).queryByText("No nets yet.")).not.toBeInTheDocument();
  });
});
