import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createTestQueryClient, renderInRouter } from "../../test/render";
import {
  acceptMoveUnit,
  acceptRelabelUnit,
  acceptRetireUnit,
  acceptUnretireUnit,
  aLocation,
  aRevisionRef,
  aUnit,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithLocations,
  respondWithRevisionRef,
  respondWithUnitsOfPart,
} from "../../test/server";
import { UnitsList } from "./UnitsList";

const PART = "0199cccc-0000-7000-8000-000000000001";

const drawer = aLocation({
  id: "0199ffff-0000-7000-8000-000000000002",
  name: "Drawer 3",
  code: "WX-L-0002",
});

const board = aUnit({
  id: "0199dddd-0000-7000-8000-0000000000c1",
  code: "WX-U-0001",
  serial: "SN-42",
  mac: "aa:bb:cc:dd:ee:ff",
  location: {
    id: drawer.id,
    parent_id: drawer.parent_id,
    code: drawer.code,
    name: drawer.name,
    created_at: drawer.created_at,
  },
});

function renderList(units = [board]) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  respondWithLocations([drawer]);
  respondWithUnitsOfPart(PART, units);
  const queryClient = createTestQueryClient();
  return renderInRouter(<UnitsList partId={PART} />, { queryClient });
}

describe("UnitsList", () => {
  it("shows each unit's code, serial, MAC, status and location", async () => {
    renderList();

    const row = await screen.findByRole("row", { name: /WX-U-0001/ });
    expect(within(row).getByRole("link", { name: "WX-U-0001" })).toHaveAttribute(
      "href",
      `/units/${board.id}`,
    );
    expect(within(row).getByText("SN-42")).toBeInTheDocument();
    expect(within(row).getByText("aa:bb:cc:dd:ee:ff")).toBeInTheDocument();
    expect(within(row).getByText("In stock")).toBeInTheDocument();
    expect(within(row).getByText("Drawer 3")).toBeInTheDocument();
  });

  it("reports a part with no units", async () => {
    renderList([]);

    expect(await screen.findByText("No units yet.")).toBeInTheDocument();
  });

  it("relabels a unit's serial and MAC", async () => {
    renderList();
    const sent = acceptRelabelUnit();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Relabel" }));
    const dialog = screen.getByRole("dialog", { name: "Relabel WX-U-0001" });
    const serial = within(dialog).getByRole("textbox", { name: "Serial" });
    await user.clear(serial);
    await user.type(serial, "SN-99");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ serial: "SN-99", mac: "aa:bb:cc:dd:ee:ff" });
  });

  it("shows the canonical MAC only once the input is a full address", async () => {
    renderList();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Relabel" }));
    const dialog = screen.getByRole("dialog", { name: "Relabel WX-U-0001" });
    const mac = within(dialog).getByRole("textbox", { name: "MAC" });
    await user.clear(mac);
    await user.type(mac, "AA-BB-CC-DD-EE");

    // Not six octets yet: the input isn't rewritten and it's flagged, not previewed.
    expect(within(dialog).getByRole("alert")).toHaveTextContent("isn't a MAC address");
    expect(within(dialog).queryByText(/Will be saved as/)).not.toBeInTheDocument();

    await user.type(mac, "-01");
    expect(within(dialog).getByText("Will be saved as aa:bb:cc:dd:ee:01")).toBeInTheDocument();
    expect(mac).toHaveValue("AA-BB-CC-DD-EE-01");
  });

  it("moves a unit to another location", async () => {
    const box = aLocation({
      id: "0199ffff-0000-7000-8000-000000000003",
      name: "Box",
      code: "WX-L-0003",
    });
    respondWithApiVersion("0.0.0");
    respondAsLoggedIn();
    respondWithLocations([drawer, box]);
    respondWithUnitsOfPart(PART, [board]);
    renderInRouter(<UnitsList partId={PART} />, { queryClient: createTestQueryClient() });
    const sent = acceptMoveUnit();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Move" }));
    const dialog = screen.getByRole("dialog", { name: "Move WX-U-0001" });
    const toBox = within(dialog).getByRole("combobox", { name: "To" });
    await user.selectOptions(toBox, within(toBox).getByRole("option", { name: /Box/ }));
    await user.click(within(dialog).getByRole("button", { name: "Move" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ to_location_id: box.id });
  });

  it("retires an in-stock unit with a reason", async () => {
    renderList();
    const sent = acceptRetireUnit();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Retire" }));
    const dialog = screen.getByRole("dialog", { name: "Retire WX-U-0001" });
    await user.selectOptions(
      within(dialog).getByRole("combobox", { name: "Reason" }),
      within(dialog).getByRole("option", { name: "Lost" }),
    );
    await user.click(within(dialog).getByRole("button", { name: "Retire" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toBe("lost");
  });

  it("un-retires a retired unit in one click", async () => {
    renderList([aUnit({ ...board, status: "retired" })]);
    const calls = acceptUnretireUnit();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Un-retire" }));

    await expect.poll(() => calls.count).toBe(1);
    // A retired unit offers un-retire, not retire or move.
    expect(screen.queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
  });

  it("links a reserved unit to its revision and offers only relabel", async () => {
    const ref = aRevisionRef({
      id: "0199eeee-0000-7000-8000-000000000001",
      label: "A",
      summary: "breadboard",
      project_name: "Greenhouse controller",
    });
    respondWithRevisionRef(ref);
    renderList([aUnit({ ...board, status: "reserved", revision_id: ref.id, location: null })]);

    const row = await screen.findByRole("row", { name: /WX-U-0001/ });
    expect(within(row).getByText("Reserved")).toBeInTheDocument();
    // The revision it is held for is shown as a link, in place of a location.
    expect(await within(row).findByRole("link", { name: /Greenhouse controller/ })).toHaveAttribute(
      "href",
      `/projects/${ref.project_id}/revisions/${ref.id}`,
    );
    // A held unit can be relabelled but not moved or retired.
    expect(within(row).getByRole("button", { name: "Relabel" })).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Move" })).not.toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Un-retire" })).not.toBeInTheDocument();
  });

  it("links a built-in unit to its revision and offers no move or retire", async () => {
    const ref = aRevisionRef({
      id: "0199eeee-0000-7000-8000-000000000002",
      label: "A",
      summary: "",
      project_name: "Greenhouse controller",
    });
    respondWithRevisionRef(ref);
    // A unit in use answers no location; the revision link stands in for it.
    renderList([aUnit({ ...board, status: "in_use", revision_id: ref.id, location: null })]);

    const row = await screen.findByRole("row", { name: /WX-U-0001/ });
    expect(within(row).getByText("In use")).toBeInTheDocument();
    expect(
      await within(row).findByRole("link", { name: /Greenhouse controller/ }),
    ).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Move" })).not.toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
  });
});
