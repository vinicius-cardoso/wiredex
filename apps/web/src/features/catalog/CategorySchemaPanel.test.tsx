import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "../../test/render";
import {
  aCategory,
  acceptAttributeEdits,
  acceptAttributeRemoval,
  acceptNewAttributes,
  anAttribute,
  respondWithCategories,
  respondWithCategorySchema,
  server,
} from "../../test/server";
import { CategorySchemaPanel } from "./CategorySchemaPanel";

const passives = aCategory({ name: "Passives", child_count: 1 });
const resistors = aCategory({
  id: "0199bbbb-0000-7000-8000-000000000002",
  parent_id: passives.id,
  name: "Resistors",
});

const rohs = anAttribute({
  id: "0199dddd-0000-7000-8000-00000000000a",
  category_id: passives.id,
  key: "rohs",
  label: "RoHS",
  kind: "bool",
  unit: null,
  required: false,
  inherited: true,
});
const resistance = anAttribute({ category_id: resistors.id, label: "Resistance", unit: "Ω" });

function renderPanel(attributes = [rohs, resistance]) {
  respondWithCategories([passives, resistors]);
  respondWithCategorySchema(resistors, attributes);
  renderWithProviders(<CategorySchemaPanel category={resistors} />);
}

function panel() {
  return screen.getByRole("region", { name: "Fields of Resistors" });
}

describe("CategorySchemaPanel", () => {
  it("tells the category's own fields from the ones it inherits", async () => {
    renderPanel();

    const fields = within(await screen.findByRole("list")).getAllByRole("listitem");

    expect(fields[0]).toHaveTextContent("RoHS");
    expect(fields[0]).toHaveTextContent("From Passives");
    // An inherited field belongs to the category above, so it isn't changed from here.
    expect(within(fields[0] as HTMLElement).queryByRole("button")).toBeNull();
    expect(fields[1]).toHaveTextContent("Resistance");
    expect(fields[1]).toHaveTextContent("Ω");
    expect(fields[1]).toHaveTextContent("Required");
    expect(within(fields[1] as HTMLElement).getByRole("button", { name: "Edit Resistance" }));
  });

  it("adds a field, asking for the options a choice needs", async () => {
    renderPanel([]);
    const sent = acceptNewAttributes();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Add a field" }));
    await user.type(within(panel()).getByRole("textbox", { name: "Key" }), "tolerance");
    await user.type(within(panel()).getByRole("textbox", { name: "Label" }), "Tolerance");
    await user.selectOptions(
      within(panel()).getByRole("combobox", { name: "Kind" }),
      screen.getByRole("option", { name: "Choice" }),
    );
    await user.type(within(panel()).getByRole("textbox", { name: "Options" }), "1%\n5%");
    await user.click(within(panel()).getByRole("checkbox", { name: "Required" }));
    await user.click(within(panel()).getByRole("button", { name: "Save" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({
      key: "tolerance",
      label: "Tolerance",
      kind: "enum",
      unit: null,
      required: true,
      options: ["1%", "5%"],
      position: 0,
    });
  });

  it("edits a field without touching its key or kind", async () => {
    renderPanel();
    const sent = acceptAttributeEdits();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Edit Resistance" }));
    const label = within(panel()).getByRole("textbox", { name: "Label" });
    await user.clear(label);
    await user.type(label, "Resistance (nominal)");
    await user.click(within(panel()).getByRole("button", { name: "Save" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ label: "Resistance (nominal)", required: true, options: [] });
    expect(within(panel()).queryByRole("textbox", { name: "Label" })).toBeNull();
  });

  it("removes a field, which keeps the values stored under it", async () => {
    renderPanel();
    acceptAttributeRemoval();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Remove Resistance" }));

    // The API answers 204 and the schema is refetched; nothing is said about the values,
    // which is the point: they stay, and their parts get flagged on read.
    await expect.poll(() => screen.queryByRole("alert")).toBeNull();
  });

  it("says when a category declares no fields yet", async () => {
    renderPanel([]);

    expect(await screen.findByText(/No fields yet/)).toBeInTheDocument();
  });

  it("shows what the API refuses, where it was asked", async () => {
    renderPanel([]);
    server.use(
      http.post("*/api/catalog/categories/:categoryId/attributes", () =>
        HttpResponse.json({ detail: "resistance is already defined by Passives" }, { status: 409 }),
      ),
    );
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Add a field" }));
    await user.type(within(panel()).getByRole("textbox", { name: "Key" }), "resistance");
    await user.type(within(panel()).getByRole("textbox", { name: "Label" }), "Resistance");
    await user.click(within(panel()).getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("already defined by Passives");
    // The form stays open, holding what was typed.
    expect(within(panel()).getByRole("textbox", { name: "Key" })).toHaveValue("resistance");
  });
});
