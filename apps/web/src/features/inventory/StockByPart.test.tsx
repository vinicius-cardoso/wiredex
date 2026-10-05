import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PartHolding, PartStock } from "@wiredex/api-client";
import { describe, expect, it } from "vitest";
import { createTestQueryClient, renderInRouter } from "../../test/render";
import {
  aBalance,
  acceptAdjust,
  acceptMove,
  acceptReceive,
  acceptReceiveUnits,
  aLocation,
  aLotBalance,
  aPartHolding,
  aPartStock,
  aRevisionRef,
  aUnit,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithLocations,
  respondWithPartHoldings,
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

const stock = aPartStock([aLotBalance(drawer, 100)]);

function renderStock(held: PartStock = stock, holdings: PartHolding[] = []) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  respondWithLocations([drawer, box]);
  respondWithPartStock(PART, held);
  respondWithPartHoldings(PART, holdings);
  const queryClient = createTestQueryClient();
  renderInRouter(<StockByPart partId={PART} />, { queryClient });
}

describe("StockByPart", () => {
  it("shows on hand, reserved and available in total and per location", async () => {
    renderStock(aPartStock([aLotBalance(drawer, 100, { reserved: 30 })]));

    expect(await screen.findByText("100 in stock")).toBeInTheDocument();
    expect(screen.getByText("30 reserved")).toBeInTheDocument();
    expect(screen.getByText("70 available")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Stock by location" });
    const row = within(table).getByRole("row", { name: /Drawer 3/ });
    expect(within(row).getByText("WX-L-0002")).toBeInTheDocument();
    const cells = within(row).getAllByRole("cell");
    expect(cells.map((cell) => cell.textContent)).toEqual(["100", "30", "70"]);
  });

  it("labels each number for when the breakdown stacks into cards", async () => {
    renderStock();

    const table = await screen.findByRole("table", { name: "Stock by location" });
    expect(table.parentElement).toHaveAttribute("data-stack", "xs");
    const row = within(table).getByRole("row", { name: /Drawer 3/ });
    // The location names the card, so it carries no label of its own.
    expect(within(row).getByRole("rowheader")).not.toHaveAttribute("data-label");
    const labels = within(row)
      .getAllByRole("cell")
      .map((cell) => cell.getAttribute("data-label"));
    expect(labels).toEqual(["On hand", "Reserved", "Available"]);
  });

  it("is a block named Stock", async () => {
    renderStock();

    const section = await screen.findByRole("region", { name: "Stock" });
    expect(within(section).getByRole("heading", { level: 2, name: "Stock" })).toBeInTheDocument();
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
    respondWithPartStock(PART, aPartStock([aLotBalance(drawer, 150)]));
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
    renderStock(aPartStock());

    expect(await screen.findByText("0 in stock")).toBeInTheDocument();
    expect(screen.getByText(/None in stock yet/)).toBeInTheDocument();
  });

  it("refuses a recount below what a build reserves at the location, without asking the API", async () => {
    renderStock(aPartStock([aLotBalance(drawer, 100, { reserved: 30 })]));
    const sent = acceptAdjust();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Adjust" }));
    const dialog = screen.getByRole("dialog", { name: "Adjust stock" });
    await user.selectOptions(
      within(dialog).getByRole("combobox", { name: "Location" }),
      within(dialog).getByRole("option", { name: /Drawer 3/ }),
    );
    await user.type(within(dialog).getByRole("spinbutton", { name: "Counted quantity" }), "20");

    expect(within(dialog).getByRole("alert")).toHaveTextContent(/30 are reserved/);
    expect(within(dialog).getByRole("button", { name: "Adjust" })).toBeDisabled();
    expect(sent.length).toBe(0);
  });

  it("refuses a move above the location's available stock, without asking the API", async () => {
    renderStock(aPartStock([aLotBalance(drawer, 100, { reserved: 30 })]));
    const sent = acceptMove();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Move" }));
    const dialog = screen.getByRole("dialog", { name: "Move stock" });
    const fromBox = within(dialog).getByRole("combobox", { name: "From" });
    const toBox = within(dialog).getByRole("combobox", { name: "To" });
    await user.selectOptions(fromBox, within(fromBox).getByRole("option", { name: /Drawer 3/ }));
    await user.selectOptions(toBox, within(toBox).getByRole("option", { name: /Parts box/ }));
    await user.type(within(dialog).getByRole("spinbutton", { name: "Quantity" }), "80");

    expect(within(dialog).getByRole("alert")).toHaveTextContent(/70 are available/);
    expect(within(dialog).getByRole("button", { name: "Move" })).toBeDisabled();
    expect(sent.length).toBe(0);
  });

  it("shows the builds holding the part beneath the breakdown, linking to each", async () => {
    renderStock(stock, [
      aPartHolding({
        revision: aRevisionRef({
          project_name: "Greenhouse controller",
          label: "A",
          summary: null,
        }),
        reserved: 3,
      }),
    ]);

    const section = await screen.findByRole("region", { name: "Held for builds" });
    expect(
      await within(section).findByRole("link", { name: /Greenhouse controller/ }),
    ).toBeInTheDocument();
    expect(within(section).getByText("3 reserved")).toBeInTheDocument();
  });
});

describe("StockByPart, unit-tracked", () => {
  function renderUnitTracked(units = [aUnit({ code: "WX-U-0001" })]) {
    respondWithApiVersion("0.0.0");
    respondAsLoggedIn();
    respondWithLocations([drawer, box]);
    respondWithPartStock(PART, stock);
    respondWithPartHoldings(PART, []);
    respondWithUnitsOfPart(PART, units);
    renderInRouter(<StockByPart partId={PART} unitTracked />, {
      queryClient: createTestQueryClient(),
    });
  }

  it("offers Receive units and no loose recount or move", async () => {
    renderUnitTracked();

    expect(await screen.findByRole("button", { name: "Receive units" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Receive" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Adjust" })).not.toBeInTheDocument();
    // The loose move is refused for this part; its units move one by one from their own list,
    // which the part page shows as a block of its own.
    expect(screen.queryByRole("button", { name: "Move" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Units" })).not.toBeInTheDocument();
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

describe("StockByPart, not stocked", () => {
  function renderConsumable(held: typeof stock, props: { unitTracked?: boolean } = {}) {
    respondWithApiVersion("0.0.0");
    respondAsLoggedIn();
    respondWithLocations([drawer, box]);
    respondWithPartStock(PART, held);
    respondWithPartHoldings(PART, []);
    respondWithUnitsOfPart(PART, [aUnit({ code: "WX-U-0001" })]);
    renderInRouter(<StockByPart partId={PART} notStocked {...props} />, {
      queryClient: createTestQueryClient(),
    });
  }

  it("says a consumable isn't stocked and offers nothing while it holds nothing", async () => {
    // 09's requirement 11.11: no receipt, and nothing held to recount or move.
    renderConsumable(aPartStock());

    const section = await screen.findByRole("region", { name: "Stock" });
    expect(await within(section).findByText(/None in stock yet/)).toBeInTheDocument();
    expect(
      within(section).getByText(/Not stocked: this part's category is for consumables/),
    ).toBeInTheDocument();
    expect(within(section).queryByText(/can still be recounted/)).not.toBeInTheDocument();
    expect(within(section).queryByRole("button")).not.toBeInTheDocument();
  });

  it("keeps Adjust and Move for what a consumable held before, but no Receive", async () => {
    // 09's requirement 2.3: stock held before the flag was set keeps working.
    renderConsumable(stock);

    expect(await screen.findByText("100 in stock")).toBeInTheDocument();
    expect(screen.getByText(/can still be recounted and moved/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Adjust" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Move" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Receive" })).not.toBeInTheDocument();
  });

  it("offers a tracked consumable no receipt and no loose recount", async () => {
    // 09's requirement 2.4: received as nothing; its units, listed by the part page, still
    // move one by one.
    renderConsumable(stock, { unitTracked: true });

    expect(await screen.findByText("100 in stock")).toBeInTheDocument();
    expect(screen.getByText(/Not stocked/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Receive units" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Adjust" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Move" })).not.toBeInTheDocument();
  });
});
