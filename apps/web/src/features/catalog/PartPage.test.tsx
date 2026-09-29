import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
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
  aPartStock,
  refusePartDeletion,
  refusePartSaves,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithAttachments,
  respondWithCategories,
  respondWithCategorySchema,
  respondWithLocations,
  respondWithPart,
  respondWithPartHoldings,
  respondWithPartStock,
  respondWithParts,
  respondWithUnitsOfPart,
  server,
} from "../../test/server";
import { subjectOfPart } from "../files/attachments";

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
  respondWithAttachments(subjectOfPart(served.id), []);
  // The part page now mounts the stock section, which asks for the part's stock and the
  // location list; served empty here, since these tests are about the catalog part itself.
  respondWithLocations([]);
  respondWithPartStock(served.id, aPartStock());
  respondWithPartHoldings(served.id, []);
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

  it("duplicates the part into quick-add, the name selected and the part number blank", async () => {
    const pulledOne = aPartDetails({
      ...resistor,
      attributes: { ...resistor.attributes, pulled: { value: true, display: "true", unit: null } },
    });
    renderPartPage(pulledOne);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Duplicate" }));

    const dialog = await screen.findByRole("dialog", { name: `Duplicate ${resistor.name}` });
    const inside = within(dialog);
    const name = await inside.findByRole("textbox", { name: "Name" });
    await expect.poll(() => document.activeElement).toBe(name);
    expect(name).toHaveValue(resistor.name);
    expect(name).toHaveProperty("selectionStart", 0);
    expect(name).toHaveProperty("selectionEnd", resistor.name.length);
    expect(inside.getByRole("textbox", { name: "Part number" })).toHaveValue("");
    expect(inside.getByRole("combobox", { name: "Category" })).toHaveValue(resistors.id);
    expect(inside.getByRole("textbox", { name: "Manufacturer" })).toHaveValue(
      resistor.manufacturer,
    );
    expect(inside.getByRole("textbox", { name: "Package" })).toHaveValue(resistor.package);
    // The values as the page shows them: engineering notation, and the switch as stored.
    expect(await inside.findByRole("textbox", { name: "Resistance" })).toHaveValue("4.7k");
    expect(inside.getByRole("switch", { name: "Pulled from a board" })).toBeChecked();
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

  it("names the bills of materials that keep a part it refuses to delete", async () => {
    // 09's requirement 11.13: each BOM a link to its revision, and how many more.
    renderPartPage();
    const station = "0199aaaa-0000-7000-8000-000000000001";
    refusePartDeletion(
      [
        {
          project_id: station,
          project_name: "Weather station",
          revision_id: "0199aaaa-0000-7000-8000-00000000000a",
          revision_label: "A",
        },
        {
          project_id: station,
          project_name: "Weather station",
          revision_id: "0199aaaa-0000-7000-8000-00000000000b",
          revision_label: "B",
        },
      ],
      2,
    );
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete part" }));

    const refusal = await screen.findByRole("alert");
    expect(refusal).toHaveTextContent("Take it off these first");
    expect(
      within(refusal).getByRole("link", { name: "Weather station, revision A" }),
    ).toHaveAttribute(
      "href",
      `/projects/${station}/revisions/0199aaaa-0000-7000-8000-00000000000a`,
    );
    expect(
      within(refusal).getByRole("link", { name: "Weather station, revision B" }),
    ).toBeInTheDocument();
    expect(refusal).toHaveTextContent("And 2 more.");
    // Still on the part, which is still there.
    expect(screen.getByRole("heading", { level: 1, name: resistor.name })).toBeInTheDocument();
  });

  it("says a deletion failed when nothing names why", async () => {
    renderPartPage();
    server.use(
      http.delete("*/api/catalog/parts/:partId", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete part" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The part couldn't be deleted.");
    expect(screen.queryByRole("link", { name: /revision/ })).not.toBeInTheDocument();
  });

  it("opens the pinout editor from the pinout section, and closes it again", async () => {
    renderPartPage();
    const user = userEvent.setup();

    // This part has no pins, so the section offers to add them instead of listing them.
    await user.click(await screen.findByRole("button", { name: "Add a pinout" }));

    expect(await screen.findByRole("heading", { name: "Edit the pinout" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(await screen.findByRole("button", { name: "Add a pinout" })).toBeInTheDocument();
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

describe("a part's stock, by the part's own flags", () => {
  it("receives units for a part that resolves tracked, whatever the schema read says", async () => {
    // 09's requirement 1.5: the flags come with the part. The category here says nothing is
    // tracked, so only the part's answer can offer units.
    renderPartPage(aPartDetails({ ...resistor, tracked_individually: true }));
    respondWithUnitsOfPart(resistor.id, []);

    expect(await screen.findByRole("button", { name: "Receive units" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Receive" })).not.toBeInTheDocument();
  });

  it("says a not-stocked part isn't stocked and offers no receipt", async () => {
    // 09's requirement 11.11.
    renderPartPage(aPartDetails({ ...resistor, not_stocked: true }));

    const section = await screen.findByRole("region", { name: "Stock" });
    expect(await within(section).findByText(/Not stocked/)).toBeInTheDocument();
    expect(within(section).queryByRole("button", { name: "Receive" })).not.toBeInTheDocument();
    expect(within(section).queryByRole("button", { name: "Adjust" })).not.toBeInTheDocument();
  });

  it("receives a lot for a part that resolves neither flag", async () => {
    renderPartPage();

    const section = await screen.findByRole("region", { name: "Stock" });
    expect(within(section).getByRole("button", { name: "Receive" })).toBeInTheDocument();
    expect(within(section).queryByText(/Not stocked/)).not.toBeInTheDocument();
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
