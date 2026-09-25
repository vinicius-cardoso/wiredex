import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PartDetails } from "@wiredex/api-client";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aCategory,
  acceptPartDeletion,
  acceptPartSaves,
  anAttribute,
  aPartDetails,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithCategories,
  respondWithCategorySchema,
  respondWithPart,
  respondWithParts,
} from "../../test/server";

const resistors = aCategory({ name: "Resistors" });

const resistance = anAttribute({ key: "resistance", label: "Resistance", unit: "Ω" });
const pulled = anAttribute({
  id: "0199dddd-0000-7000-8000-000000000004",
  key: "pulled",
  label: "Pulled from a board",
  kind: "bool",
  unit: null,
  required: false,
  position: 1,
});

const resistor = aPartDetails({
  name: "4.7 kΩ 1% 0805",
  category_id: resistors.id,
  attributes: {
    resistance: { value: "4700", display: "4.7k", unit: "Ω" },
    pulled: { value: false, display: "false", unit: null },
  },
});

/** Serves `served` for any part id, so a different id is how a part goes missing. */
function renderPartPage(served: PartDetails = resistor) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  respondWithCategories([resistors]);
  respondWithCategorySchema(resistors, [resistance, pulled]);
  respondWithPart(served);
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: [`/parts/${resistor.id}`] });
  renderWithProviders(<RouterProvider router={createAppRouter(queryClient, history)} />, {
    queryClient,
  });
}

describe("PartPage", () => {
  it("shows the part with its attributes in engineering notation", async () => {
    renderPartPage();

    expect(
      await screen.findByRole("heading", { level: 1, name: resistor.name }),
    ).toBeInTheDocument();

    await screen.findByText("4.7kΩ"); // The fields arrive with the category's schema.
    const values = screen.getAllByRole("definition").map((entry) => entry.textContent);
    expect(values).toContain("4.7kΩ");
    expect(values).toContain("No"); // The switch that is off, in words.
    expect(values).toContain("Resistors");
  });

  it("edits the part, starting from what is stored", async () => {
    renderPartPage();
    const sent = acceptPartSaves(resistor);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Edit" }));

    const field = await screen.findByRole("textbox", { name: "Resistance" });
    expect(field).toHaveValue("4.7k");

    await user.clear(field);
    await user.type(field, "10k");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]?.attributes).toEqual({ resistance: "10k", pulled: false });
    // Saving closes the form and shows the part again.
    expect(await screen.findByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it("asks before deleting, then returns to the list", async () => {
    renderPartPage();
    respondWithParts([]);
    acceptPartDeletion();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete" }));

    const question = screen.getByRole("group", { name: "Delete this part?" });
    expect(question).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete part" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Parts" })).toBeInTheDocument();
  });

  it("says so when the part can't be found", async () => {
    renderPartPage(aPartDetails({ id: "0199cccc-0000-7000-8000-00000000ffff" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't be loaded");
  });
});
