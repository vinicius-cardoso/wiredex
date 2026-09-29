import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { createTestQueryClient, renderInRouter } from "../../../test/render";
import {
  aBom,
  aBomPart,
  aBomPartFacts,
  acceptTransitions,
  aRevision,
  aUnit,
  refuseTransition,
  respondWithBom,
  respondWithUnitsOfPart,
} from "../../../test/server";
import { ReserveDialog } from "./ReserveDialog";

const revision = aRevision({ status: "draft" });
const esp32 = "0199cccc-0000-7000-8000-0000000000e1";
const resistor = "0199cccc-0000-7000-8000-0000000000e2";
const flux = "0199cccc-0000-7000-8000-0000000000e3";

const unitOne = aUnit({
  id: "0199dddd-0000-7000-8000-000000000101",
  part_id: esp32,
  code: "WX-U-0001",
});
const unitTwo = aUnit({
  id: "0199dddd-0000-7000-8000-000000000102",
  part_id: esp32,
  code: "WX-U-0002",
});

/** A BOM with a unit-tracked ESP32 (need 1), a stocked resistor and a flux consumable. */
function aReserveBom() {
  return aBom(
    {
      parts: [
        aBomPart({
          part_id: esp32,
          need: 1,
          part: aBomPartFacts({ name: "ESP32-WROOM", tracked_individually: true }),
        }),
        aBomPart({
          part_id: resistor,
          need: 3,
          part: aBomPartFacts({ name: "10k 0805" }),
        }),
        aBomPart({
          part_id: flux,
          need: 1,
          available: null,
          status: "not_stocked",
          part: aBomPartFacts({ name: "Flux", not_stocked: true }),
        }),
      ],
    },
    { revision_id: revision.id },
  );
}

function renderDialog(onClose = vi.fn()) {
  respondWithBom(aReserveBom());
  respondWithUnitsOfPart(esp32, [unitOne, unitTwo]);
  const queryClient = createTestQueryClient();
  renderInRouter(<ReserveDialog revisionId={revision.id} onClose={onClose} />, { queryClient });
  return { onClose };
}

describe("ReserveDialog", () => {
  it("lists what will be reserved, names the consumables, and reserves automatically", async () => {
    const reserves = acceptTransitions();
    const { onClose } = renderDialog();
    const user = userEvent.setup();

    const dialog = await screen.findByRole("dialog", { name: "Reserve parts" });
    const willReserve = await within(dialog).findByRole("region", {
      name: "What will be reserved",
    });
    expect(willReserve).toHaveTextContent("ESP32-WROOM");
    expect(willReserve).toHaveTextContent("10k 0805");

    const consumables = within(dialog).getByRole("region", { name: "Not reserved" });
    expect(consumables).toHaveTextContent("Flux");

    // No box checked means the automatic choice: an empty units list is sent.
    await user.click(within(dialog).getByRole("button", { name: "Reserve" }));
    expect(reserves.reserves).toEqual([{ units: [] }]);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("offers a checkbox per in-stock board and names the ones chosen", async () => {
    const reserves = acceptTransitions();
    renderDialog();
    const user = userEvent.setup();

    const dialog = await screen.findByRole("dialog", { name: "Reserve parts" });
    const first = await within(dialog).findByRole("checkbox", { name: "WX-U-0001" });
    const second = within(dialog).getByRole("checkbox", { name: "WX-U-0002" });

    // The ESP32 needs one, so once one is checked the other disables (requirement 13.2).
    await user.click(first);
    expect(second).toBeDisabled();

    await user.click(within(dialog).getByRole("button", { name: "Reserve" }));
    expect(reserves.reserves).toEqual([{ units: [unitOne.id] }]);
  });

  it("shows the shortage report inside the dialog when the reserve is short", async () => {
    refuseTransition("reserve", {
      code: "short",
      report: aReserveBom().report,
    });
    renderDialog();
    const user = userEvent.setup();

    const dialog = await screen.findByRole("dialog", { name: "Reserve parts" });
    await user.click(await within(dialog).findByRole("button", { name: "Reserve" }));

    expect(await within(dialog).findByRole("region", { name: "Shortages" })).toBeInTheDocument();
  });

  it("shows a unit refusal in the dialog, in the reader's language", async () => {
    refuseTransition("reserve", { code: "unit_not_in_stock", unit_code: "WX-U-0002" });
    renderDialog();
    const user = userEvent.setup();

    const dialog = await screen.findByRole("dialog", { name: "Reserve parts" });
    await user.click(await within(dialog).findByRole("button", { name: "Reserve" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Board WX-U-0002 isn't in stock.",
    );
  });
});
