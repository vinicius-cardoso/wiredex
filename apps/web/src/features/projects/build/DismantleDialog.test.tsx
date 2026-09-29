import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { createTestQueryClient, renderWithProviders } from "../../../test/render";
import {
  acceptTransitions,
  aLocation,
  refuseTransition,
  respondWithLocations,
} from "../../../test/server";
import { DismantleDialog } from "./DismantleDialog";

const REVISION_ID = "0199eeee-0000-7000-8000-00000000000a";
const drawer = aLocation({ id: aLocation().id, name: "Drawer 3", code: "WX-L-0003" });

function renderDialog(onClose = vi.fn()) {
  respondWithLocations([drawer]);
  const queryClient = createTestQueryClient();
  renderWithProviders(<DismantleDialog revisionId={REVISION_ID} onClose={onClose} />, {
    queryClient,
  });
  return { onClose };
}

describe("DismantleDialog", () => {
  it("says everything returns to the chosen location, and dismantles there", async () => {
    const dismantles = acceptTransitions();
    const { onClose } = renderDialog();
    const user = userEvent.setup();

    const dialog = screen.getByRole("dialog", { name: "Dismantle the build" });
    expect(dialog).toHaveTextContent(
      "Everything the build used returns to the location you choose.",
    );

    // The send is disabled until a location is picked (requirement 13.5).
    const confirm = within(dialog).getByRole("button", { name: "Dismantle it" });
    expect(confirm).toBeDisabled();

    const picker = within(dialog).getByRole("combobox", { name: "Return to" });
    await user.type(picker, "drawer 3");
    await user.click(await screen.findByRole("option", { name: /Drawer 3/ }));

    expect(confirm).toBeEnabled();
    await user.click(confirm);

    expect(dismantles.dismantles).toEqual([{ location_id: drawer.id }]);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows an unknown location refusal in the dialog", async () => {
    refuseTransition("dismantle", { code: "unknown_location" }, 422);
    renderDialog();
    const user = userEvent.setup();

    const dialog = screen.getByRole("dialog", { name: "Dismantle the build" });
    await user.type(within(dialog).getByRole("combobox", { name: "Return to" }), "drawer 3");
    await user.click(await screen.findByRole("option", { name: /Drawer 3/ }));
    await user.click(within(dialog).getByRole("button", { name: "Dismantle it" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "That location isn't in this workspace.",
    );
  });
});
