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
  it("lists a field an inherited one of the same key hides, to be removed", async () => {
    // Stored before the API refused to make one: it made every read of the category fail.
    const { inherited: _, ...own } = anAttribute({
      id: "0199dddd-0000-7000-8000-00000000000b",
      category_id: resistors.id,
      key: "rohs",
      label: "RoHS compliant",
      kind: "bool",
      unit: null,
    });
    const removed: string[] = [];
    respondWithCategories([passives, resistors]);
    respondWithCategorySchema(resistors, [rohs, resistance], [{ ...own, hidden_by: passives.id }]);
    server.use(
      http.delete("*/api/catalog/attributes/:attributeId", ({ params }) => {
        removed.push(String(params.attributeId));
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithProviders(<CategorySchemaPanel category={resistors} />);
    const user = userEvent.setup();

    expect(
      await within(panel()).findByText("RoHS compliant (rohs), hidden by the field of Passives"),
    ).toBeInTheDocument();
    expect(
      within(panel()).getByText(/the inherited one applies and these do nothing/),
    ).toBeVisible();
    // The table still shows the one that applies, once.
    expect(within(panel()).getAllByRole("row")).toHaveLength(3);

    await user.click(
      within(panel()).getByRole("button", { name: "Remove the hidden field RoHS compliant" }),
    );
    await expect.poll(() => removed).toEqual([own.id]);
  });

  it("shows no hidden fields where no key is defined twice", async () => {
    renderPanel();
    await within(panel()).findByRole("table", { name: "Fields" });
    expect(within(panel()).queryByText("Fields hidden by a category above")).toBeNull();
  });

  it("tells the category's own fields from the ones it inherits", async () => {
    renderPanel();

    const table = await within(panel()).findByRole("table", { name: "Fields" });
    // The heading row first, then one row per field.
    const fields = within(table).getAllByRole("row").slice(1);

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
    // A new field's key, kind and unit are still open, so nothing is said about locking.
    expect(within(panel()).queryByText(/can't change once a field exists/)).toBeNull();
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

  it("says which value a field still needs, rather than saving nothing in silence", async () => {
    renderPanel([]);
    const sent = acceptNewAttributes();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add a field" }));
    const key = within(panel()).getByRole("textbox", { name: "Key" });
    const label = within(panel()).getByRole("textbox", { name: "Label" });

    // Nothing typed: the key is asked for first, and takes the focus.
    await user.click(within(panel()).getByRole("button", { name: "Save" }));
    expect(key).toHaveAttribute("aria-invalid", "true");
    expect(key).toHaveAccessibleDescription("This needs a value.");
    expect(key).toHaveFocus();
    expect(label).not.toHaveAttribute("aria-invalid");

    // A key and no label: the label says so, and typing in it takes the message away.
    await user.type(key, "Thread");
    expect(key).not.toHaveAttribute("aria-invalid");
    await user.click(within(panel()).getByRole("button", { name: "Save" }));
    expect(label).toHaveAttribute("aria-invalid", "true");
    expect(label).toHaveAccessibleDescription("This needs a value.");
    expect(label).toHaveFocus();
    expect(sent).toHaveLength(0);

    await user.type(label, "Thread");
    expect(within(panel()).queryByText("This needs a value.")).toBeNull();
    await user.click(within(panel()).getByRole("button", { name: "Save" }));
    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toMatchObject({ key: "Thread", label: "Thread" });
  });

  it("edits a field without touching its key or kind", async () => {
    renderPanel();
    const sent = acceptAttributeEdits();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Edit Resistance" }));
    // The key, the kind and the unit are locked, and each says why and the way around it.
    const why =
      /^The key, kind and unit can't change once a field exists.+remove the field and add it again\.$/;
    const unit = within(panel()).getByRole("textbox", { name: "Unit" });
    expect(unit).toHaveAttribute("readonly");
    expect(unit).toHaveAccessibleDescription(why);
    expect(within(panel()).getByRole("textbox", { name: "Key" })).toHaveAccessibleDescription(why);
    expect(within(panel()).getByRole("combobox", { name: "Kind" })).toBeDisabled();
    await user.type(unit, "F");
    expect(unit).toHaveValue("Ω");
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
