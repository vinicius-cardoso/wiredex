import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PartDetails } from "@wiredex/api-client";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aCategory,
  acceptPartDeletion,
  acceptPartSaves,
  anAttribute,
  aPartDetails,
  refusePartSaves,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithCategories,
  respondWithCategorySchema,
  respondWithPart,
  respondWithParts,
  server,
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

  it("puts a refused edit on the field it names", async () => {
    renderPartPage();
    refusePartSaves("resistance: '10Q' is not a number in Ω — write it like 4k7, 4700 or 4.7e3");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const field = await screen.findByRole("textbox", { name: "Resistance" });
    await user.clear(field);
    await user.type(field, "10k");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText(/is not a number in/)).toBeInTheDocument();
    // Still in the form, with the value that was typed kept.
    expect(field).toHaveValue("10k");
  });

  it("shows a refusal it can't pin on a field above the buttons", async () => {
    renderPartPage();
    server.use(
      http.patch("*/api/catalog/parts/:partId", () =>
        HttpResponse.json({ detail: [{ msg: "that category doesn't exist" }] }, { status: 422 }),
      ),
    );
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    await screen.findByRole("textbox", { name: "Resistance" });
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("that category doesn't exist");
  });
});

describe("a part that needs review", () => {
  const flagged = aPartDetails({
    name: "4.7 kΩ 1% 0805",
    category_id: resistors.id,
    attributes: { depth: { value: "2", display: "2", unit: null } },
    needs_review: true,
    problems: [
      { key: "resistance", problem: "missing_required", message: "resistance is required" },
      { key: "depth", problem: "unknown_key", message: "'depth' is not an attribute" },
    ],
  });

  it("shows a banner listing what no longer fits", async () => {
    renderPartPage(flagged);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("This part needs a look");
    expect(banner).toHaveTextContent("resistance needs a value.");
    expect(banner).toHaveTextContent("depth is no longer a field of this category.");
  });

  it("keeps the value of a field nobody defines any more", async () => {
    renderPartPage(flagged);

    expect(await screen.findByText(/depth \(no longer a field\)/)).toBeInTheDocument();
  });

  it("marks the fields to fix while the part is being edited", async () => {
    renderPartPage(flagged);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Edit" }));

    const field = await screen.findByRole("textbox", { name: "Resistance" });
    expect(field).toHaveAccessibleDescription(/needs a value/);
  });
});
