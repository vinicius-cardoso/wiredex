import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createTestQueryClient, renderInRouter } from "../../test/render";
import {
  acceptDeleteUnit,
  acceptRelabelUnit,
  acceptUnretireUnit,
  aLocation,
  aUnit,
  refuseDeleteUnit,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithLocations,
  respondWithUnit,
} from "../../test/server";
import { UnitPage } from "./UnitPage";

const drawer = aLocation({ name: "Lab", code: "WX-L-0001" });

const board = aUnit({
  id: "0199dddd-0000-7000-8000-0000000000c1",
  code: "WX-U-0007",
  serial: "SN-7",
  mac: "aa:bb:cc:dd:ee:07",
});

function renderPage(unit = board) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  respondWithLocations([drawer]);
  respondWithUnit(unit);
  return renderInRouter(<UnitPage unitId={unit.id} />, { queryClient: createTestQueryClient() });
}

describe("UnitPage", () => {
  it("shows the unit's identity, status and location", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "WX-U-0007" })).toBeInTheDocument();
    expect(screen.getByText("SN-7")).toBeInTheDocument();
    expect(screen.getByText("aa:bb:cc:dd:ee:07")).toBeInTheDocument();
    expect(screen.getByText("In stock")).toBeInTheDocument();
  });

  it("hides delete while the unit is in stock, offering retire instead", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "WX-U-0007" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retire" })).toBeInTheDocument();
  });

  it("relabels the unit from its page", async () => {
    renderPage();
    const sent = acceptRelabelUnit();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Relabel" }));
    const dialog = screen.getByRole("dialog", { name: "Relabel WX-U-0007" });
    const serial = within(dialog).getByRole("textbox", { name: "Serial" });
    await user.clear(serial);
    await user.type(serial, "SN-new");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]?.serial).toBe("SN-new");
  });

  it("un-retires a retired unit from its page", async () => {
    renderPage(aUnit({ ...board, status: "retired" }));
    const calls = acceptUnretireUnit();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Un-retire" }));

    await expect.poll(() => calls.count).toBe(1);
  });

  it("offers delete once the unit is retired", async () => {
    renderPage(aUnit({ ...board, status: "retired" }));
    expect(await screen.findByRole("heading", { name: "WX-U-0007" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
  });

  it("deletes a retired unit after confirming", async () => {
    const { router } = renderPage(aUnit({ ...board, status: "retired" }));
    const sent = acceptDeleteUnit();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete unit" }));

    await expect.poll(() => sent.length).toBe(1);
    await expect.poll(() => router.state.location.pathname).toBe("/units");
  });

  it("keeps a refused delete's message beside the button", async () => {
    renderPage(aUnit({ ...board, status: "retired" }));
    refuseDeleteUnit("Retire the unit before deleting it.");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete unit" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Retire the unit before deleting it.",
    );
  });
});
