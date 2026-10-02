import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createTestQueryClient, renderInRouter } from "../../test/render";
import {
  acceptDeleteUnit,
  acceptRelabelUnit,
  acceptUnretireUnit,
  aLocation,
  aRevisionRef,
  aUnit,
  refuseDeleteUnit,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithLocations,
  respondWithRevisionRef,
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
    expect(screen.queryByRole("button", { name: "Move to trash" })).not.toBeInTheDocument();
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
    expect(screen.getByRole("button", { name: "Move to trash" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
  });

  it("shows what the board runs, and no Log a flash once it is retired", async () => {
    renderPage(aUnit({ ...board, status: "retired" }));

    const section = await screen.findByRole("region", { name: "Firmware" });
    expect(
      await within(section).findByText("No flash is logged on this board yet."),
    ).toBeInTheDocument();
    expect(within(section).queryByRole("button", { name: "Log a flash" })).not.toBeInTheDocument();
  });

  it("deletes a retired unit after confirming", async () => {
    const { router } = renderPage(aUnit({ ...board, status: "retired" }));
    const sent = acceptDeleteUnit();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Move to trash" }));
    await user.click(screen.getByRole("button", { name: "Move unit to trash" }));

    await expect.poll(() => sent.length).toBe(1);
    await expect.poll(() => router.state.location.pathname).toBe("/units");
  });

  it("keeps a refused delete's message beside the button", async () => {
    renderPage(aUnit({ ...board, status: "retired" }));
    refuseDeleteUnit("Retire the unit before deleting it.");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Move to trash" }));
    await user.click(screen.getByRole("button", { name: "Move unit to trash" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Retire the unit before deleting it.",
    );
  });

  it("shows a held unit's revision and offers only relabel", async () => {
    const ref = aRevisionRef({
      id: "0199eeee-0000-7000-8000-000000000003",
      label: "A",
      summary: "breadboard",
      project_name: "Greenhouse controller",
    });
    respondWithRevisionRef(ref);
    // A unit in use answers no location; the page shows the revision it went into instead.
    renderPage(aUnit({ ...board, status: "in_use", revision_id: ref.id, location: null }));

    expect(await screen.findByRole("heading", { name: "WX-U-0007" })).toBeInTheDocument();
    expect(screen.getByText("In use")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /Greenhouse controller/ })).toHaveAttribute(
      "href",
      `/projects/${ref.project_id}/revisions/${ref.id}`,
    );
    expect(screen.getByRole("button", { name: "Relabel" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Move" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Un-retire" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Move to trash" })).not.toBeInTheDocument();
  });
});
