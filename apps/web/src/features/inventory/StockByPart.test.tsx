import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createTestQueryClient, renderInRouter, renderWithProviders } from "../../test/render";
import {
  aBalance,
  acceptAdjust,
  acceptMove,
  acceptReceive,
  acceptReceiveUnits,
  aLocation,
  aUnit,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithLocations,
  respondWithPartStock,
  respondWithUnitsOfPart,
} from "../../test/server";
import { StockByPart } from "./StockByPart";

const PART = "0199cccc-0000-7000-8000-000000000001";

const drawer = aLocation({
  id: "0199ffff-0000-7000-8000-000000000002",
  name: "Drawer 3",
  code: "WX-L-0002",
});
const box = aLocation({
  id: "0199ffff-0000-7000-8000-000000000003",
  name: "Parts box",
  code: "WX-L-0003",
});

const stock = {
  total: 100,
  breakdown: [{ location: drawer, on_hand: 100 }],
};

function renderStock() {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  respondWithLocations([drawer, box]);
  respondWithPartStock(PART, stock);
  const queryClient = createTestQueryClient();
  renderWithProviders(<StockByPart partId={PART} />, { queryClient });
}

describe("StockByPart", () => {
  it("shows the total and the per-location breakdown", async () => {
    renderStock();

    expect(await screen.findByText("100 in stock")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Stock by location" });
    const row = within(table).getByRole("row", { name: /Drawer 3/ });
    expect(within(row).getByText("WX-L-0002")).toBeInTheDocument();
    expect(within(row).getByRole("cell", { name: "100" })).toBeInTheDocument();
  });

  it("receives stock and shows the new total in place, no reload", async () => {
    renderStock();
    const sent = acceptReceive(aBalance({ on_hand: 150 }));
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Receive" }));
    const dialog = screen.getByRole("dialog", { name: "Receive stock" });
    await user.selectOptions(
      within(dialog).getByRole("combobox", { name: "Location" }),
      within(dialog).getByRole("option", { name: /Drawer 3/ }),
    );
    await user.type(within(dialog).getByRole("spinbutton", { name: "Quantity" }), "50");

    // The refetch after the change reads a higher total, which is what the page shows.
    respondWithPartStock(PART, { total: 150, breakdown: [{ location: drawer, on_hand: 150 }] });
    await user.click(within(dialog).getByRole("button", { name: "Receive" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ part_id: PART, location_id: drawer.id, quantity: 50 });
    expect(await screen.findByText("150 in stock")).toBeInTheDocument();
  });

  it("adjusts to an absolute counted quantity with a reason, not a delta", async () => {
    renderStock();
    const sent = acceptAdjust();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Adjust" }));
    const dialog = screen.getByRole("dialog", { name: "Adjust stock" });
    await user.selectOptions(
      within(dialog).getByRole("combobox", { name: "Location" }),
      within(dialog).getByRole("option", { name: /Drawer 3/ }),
    );
    await user.type(within(dialog).getByRole("spinbutton", { name: "Counted quantity" }), "97");
    await user.selectOptions(
      within(dialog).getByRole("combobox", { name: "Reason" }),
      within(dialog).getByRole("option", { name: "Damaged" }),
    );
    await user.click(within(dialog).getByRole("button", { name: "Adjust" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({
      part_id: PART,
      location_id: drawer.id,
      counted: 97,
      reason: "damaged",
    });
  });

  it("moves a quantity between two locations", async () => {
    renderStock();
    const sent = acceptMove();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Move" }));
    const dialog = screen.getByRole("dialog", { name: "Move stock" });
    const fromBox = within(dialog).getByRole("combobox", { name: "From" });
    const toBox = within(dialog).getByRole("combobox", { name: "To" });
    await user.selectOptions(fromBox, within(fromBox).getByRole("option", { name: /Drawer 3/ }));
    await user.selectOptions(toBox, within(toBox).getByRole("option", { name: /Parts box/ }));
    await user.type(within(dialog).getByRole("spinbutton", { name: "Quantity" }), "40");
    await user.click(within(dialog).getByRole("button", { name: "Move" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({
      part_id: PART,
      from_location_id: drawer.id,
      to_location_id: box.id,
      quantity: 40,
    });
  });

  it("refuses to move between the same location, without asking the API", async () => {
    renderStock();
    const sent = acceptMove();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Move" }));
    const dialog = screen.getByRole("dialog", { name: "Move stock" });
    const fromBox = within(dialog).getByRole("combobox", { name: "From" });
    const toBox = within(dialog).getByRole("combobox", { name: "To" });
    await user.selectOptions(fromBox, within(fromBox).getByRole("option", { name: /Drawer 3/ }));
    await user.selectOptions(toBox, within(toBox).getByRole("option", { name: /Drawer 3/ }));

    expect(within(dialog).getByRole("alert")).toHaveTextContent(/two different locations/);
    expect(within(dialog).getByRole("button", { name: "Move" })).toBeDisabled();
    expect(sent.length).toBe(0);
  });

  it("reports a part with no stock as zero and an empty breakdown", async () => {
    respondWithApiVersion("0.0.0");
    respondAsLoggedIn();
    respondWithLocations([drawer, box]);
    respondWithPartStock(PART, { total: 0, breakdown: [] });
    const queryClient = createTestQueryClient();
    renderWithProviders(<StockByPart partId={PART} />, { queryClient });

    expect(await screen.findByText("0 in stock")).toBeInTheDocument();
    expect(screen.getByText(/None in stock yet/)).toBeInTheDocument();
  });
});

describe("StockByPart, unit-tracked", () => {
  function renderUnitTracked(units = [aUnit({ code: "WX-U-0001" })]) {
    respondWithApiVersion("0.0.0");
    respondAsLoggedIn();
    respondWithLocations([drawer, box]);
    respondWithPartStock(PART, stock);
    respondWithUnitsOfPart(PART, units);
    renderInRouter(<StockByPart partId={PART} unitTracked />, {
      queryClient: createTestQueryClient(),
    });
  }

  it("offers Receive units and lists the part's units", async () => {
    renderUnitTracked();

    expect(await screen.findByRole("button", { name: "Receive units" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Receive" })).not.toBeInTheDocument();
    const list = screen.getByRole("region", { name: "Units" });
    expect(await within(list).findByRole("link", { name: "WX-U-0001" })).toBeInTheDocument();
  });

  it("receives units with a per-unit serial and MAC, and shows the minted codes", async () => {
    renderUnitTracked([]);
    const sent = acceptReceiveUnits([
      aUnit({ id: "0199dddd-0000-7000-8000-0000000000c1", code: "WX-U-0001" }),
      aUnit({ id: "0199dddd-0000-7000-8000-0000000000c2", code: "WX-U-0002" }),
    ]);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Receive units" }));
    const dialog = screen.getByRole("dialog", { name: "Receive units" });
    await user.selectOptions(
      within(dialog).getByRole("combobox", { name: "Location" }),
      within(dialog).getByRole("option", { name: /Drawer 3/ }),
    );
    await user.clear(within(dialog).getByRole("spinbutton", { name: "Quantity" }));
    await user.type(within(dialog).getByRole("spinbutton", { name: "Quantity" }), "2");

    // The first unit gets a serial and a MAC typed in a forgiving spelling.
    const first = within(dialog).getByRole("group", { name: "Unit 1" });
    await user.type(within(first).getByRole("textbox", { name: "Serial" }), "SN-1");
    await user.type(within(first).getByRole("textbox", { name: "MAC" }), "AA-BB-CC-DD-EE-FF");

    await user.click(within(dialog).getByRole("button", { name: "Receive units" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({
      part_id: PART,
      location_id: drawer.id,
      units: [
        { serial: "SN-1", mac: "AA-BB-CC-DD-EE-FF" },
        { serial: null, mac: null },
      ],
    });
    expect(await screen.findByText(/WX-U-0001, WX-U-0002/)).toBeInTheDocument();
  });

  it("blocks the receive while a typed MAC isn't a full address", async () => {
    renderUnitTracked([]);
    const sent = acceptReceiveUnits([]);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Receive units" }));
    const dialog = screen.getByRole("dialog", { name: "Receive units" });
    await user.selectOptions(
      within(dialog).getByRole("combobox", { name: "Location" }),
      within(dialog).getByRole("option", { name: /Drawer 3/ }),
    );
    const first = within(dialog).getByRole("group", { name: "Unit 1" });
    await user.type(within(first).getByRole("textbox", { name: "MAC" }), "not-a-mac");

    expect(within(first).getByRole("alert")).toHaveTextContent("isn't a MAC address");
    expect(within(dialog).getByRole("button", { name: "Receive units" })).toBeDisabled();
    expect(sent.length).toBe(0);
  });
});
