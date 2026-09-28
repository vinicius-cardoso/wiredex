import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ProblemCode } from "@wiredex/api-client";
import { describe, expect, it } from "vitest";
import { createI18n } from "../../../shared/i18n/i18n";
import { renderInRouter } from "../../../test/render";
import {
  aBalance,
  aCategory,
  aCellProblem,
  acceptQuickAdds,
  aLocation,
  anAttribute,
  aPartDetails,
  aQuickAddResponse,
  aUnit,
  refuseQuickAdds,
  refuseQuickAddsAsTaken,
  refuseQuickAddsWith,
  respondWithCategories,
  respondWithCategorySchemas,
  respondWithLocations,
} from "../../../test/server";
import { problemText } from "./problems";
import { type QuickAddOptions, QuickAddProvider, useQuickAdd } from "./QuickAddProvider";

const resistors = aCategory({ name: "Resistors" });
const boards = aCategory({
  id: "0199bbbb-0000-7000-8000-000000000002",
  name: "Boards",
  tracked_individually: true,
  tracked_individually_resolved: true,
});
const resistance = anAttribute({ key: "resistance", label: "Resistance", unit: "Ω" });

const lab = aLocation({ name: "Lab", code: "WX-L-0001", child_count: 1 });
const drawer = aLocation({
  id: "0199ffff-0000-7000-8000-000000000003",
  parent_id: lab.id,
  name: "Drawer 3",
  code: "WX-L-0003",
});

const PART_ID = "0199cccc-0000-7000-8000-0000000000a7";

/** The 10k a 4k7 is duplicated from: Yageo, 0805, and no pins until a test gives it some. */
const tenK = aPartDetails({
  id: "0199cccc-0000-7000-8000-0000000000b1",
  category_id: resistors.id,
  name: "10 kΩ 1% 0805",
  mpn: "RC0805FR-0710KL",
  attributes: { resistance: { value: "10000", display: "10k", unit: "Ω" } },
});

function Opener({ options }: { options: QuickAddOptions }) {
  const quickAdd = useQuickAdd();
  return (
    <button type="button" onClick={() => quickAdd.open(options)}>
      Open quick add
    </button>
  );
}

/**
 * Opens quick-add over a bench of two categories and a drawer, and answers the dialog, found
 * by its title: *Quick add*, or *Duplicate …* for a duplicate.
 */
async function openQuickAdd(options: QuickAddOptions = {}, title = "Quick add") {
  respondWithCategories([resistors, boards]);
  respondWithCategorySchemas([
    { category: resistors, attributes: [resistance] },
    { category: boards, attributes: [] },
  ]);
  respondWithLocations([lab, drawer]);
  renderInRouter(
    <QuickAddProvider>
      <Opener options={options} />
    </QuickAddProvider>,
  );
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Open quick add" }));
  const dialog = await screen.findByRole("dialog", { name: title });
  await within(dialog).findByRole("combobox", { name: "Category" });
  return { user, dialog, field: fieldsOf(dialog) };
}

function fieldsOf(dialog: HTMLElement) {
  const inside = within(dialog);
  return {
    category: () => inside.getByRole("combobox", { name: "Category" }),
    name: () => inside.getByRole("textbox", { name: "Name" }),
    mpn: () => inside.getByRole("textbox", { name: "Part number" }),
    manufacturer: () => inside.getByRole("textbox", { name: "Manufacturer" }),
    package: () => inside.getByRole("textbox", { name: "Package" }),
    resistance: () => inside.findByRole("textbox", { name: "Resistance" }),
    location: () => inside.getByRole("combobox", { name: "Location" }),
    quantity: (name = "Quantity") => inside.getByRole("spinbutton", { name }),
  };
}

type Ui = Awaited<ReturnType<typeof openQuickAdd>>;

/** A 4k7 resistor, 25 of them into the drawer, the drawer picked by typing its name. */
async function fillAResistor({ user, dialog, field }: Ui, name = "4.7 kΩ 1% 0805") {
  await user.selectOptions(
    field.category(),
    within(dialog).getByRole("option", { name: "Resistors" }),
  );
  await user.type(await field.resistance(), "4k7");
  await user.type(field.name(), name);
  await pickTheDrawer(user, field.location());
}

async function pickTheDrawer(user: Ui["user"], location: HTMLElement) {
  await user.type(location, "drawer");
  await screen.findByRole("option", { name: /Drawer 3/ });
  // Enter picks from the open list; it doesn't submit.
  await user.keyboard("{ArrowDown}{Enter}");
  expect(location).toHaveValue("Lab / Drawer 3");
}

describe("QuickAddDialog", () => {
  it("is reached field by field with Tab, starting at the first empty one", async () => {
    const { user, field, dialog } = await openQuickAdd();

    expect(field.category()).toHaveFocus();
    const order = [
      field.name(),
      field.mpn(),
      field.manufacturer(),
      field.package(),
      field.location(),
      field.quantity(),
      within(dialog).getByRole("button", { name: "Add part" }),
      within(dialog).getByRole("button", { name: "Cancel" }),
    ];
    for (const next of order) {
      await user.tab();
      expect(next).toHaveFocus();
    }
  });

  it("adds a part with its first lot, sent with Enter, and says what it added", async () => {
    const ui = await openQuickAdd();
    const sent = acceptQuickAdds(
      aQuickAddResponse({
        part_id: PART_ID,
        name: "4.7 kΩ 1% 0805",
        balance: aBalance({ on_hand: 25 }),
      }),
    );
    await fillAResistor(ui);

    await ui.user.type(ui.field.quantity(), "25{Enter}");

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({
      part: {
        category_id: resistors.id,
        name: "4.7 kΩ 1% 0805",
        manufacturer: null,
        mpn: null,
        package: null,
        attributes: { resistance: "4k7" },
      },
      stock: { location_id: drawer.id, quantity: 25 },
    });
    const status = await within(ui.dialog).findByRole("status");
    await expect
      .poll(() => status.textContent)
      .toBe("Added 4.7 kΩ 1% 0805. In stock at Lab / Drawer 3: 25.");
    expect(within(ui.dialog).getByRole("button", { name: "Add another" })).toHaveFocus();
    expect(within(ui.dialog).getByRole("link", { name: "Open the part" })).toHaveAttribute(
      "href",
      `/parts/${PART_ID}`,
    );
  });

  it("receives units for a category tracked individually, and lists their codes", async () => {
    const { user, dialog, field } = await openQuickAdd();
    const minted = [aUnit({ code: "WX-U-0041" }), aUnit({ id: "u-2", code: "WX-U-0042" })];
    const sent = acceptQuickAdds(aQuickAddResponse({ name: "ESP32 DevKit", units: minted }));

    await user.selectOptions(
      field.category(),
      within(dialog).getByRole("option", { name: "Boards" }),
    );
    await user.type(field.name(), "ESP32 DevKit");
    await pickTheDrawer(user, field.location());
    const units = field.quantity("Units");
    expect(units).toHaveAccessibleDescription(/every unit gets its own WX-U code/);

    // A receipt takes at most 100 units, so 101 never leaves the form.
    await user.type(units, "101{Enter}");
    expect(units).toHaveAccessibleDescription(/A whole number from 1 to 100\./);
    expect(units).toBeInvalid();
    expect(sent).toHaveLength(0);

    await user.clear(units);
    await user.type(units, "2{Enter}");

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]?.stock).toEqual({ location_id: drawer.id, quantity: 2 });
    const codes = await within(dialog).findByRole("list", { name: "Unit codes" });
    expect(
      within(codes)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["WX-U-0041", "WX-U-0042"]);
    expect(within(dialog).getByRole("status")).toHaveTextContent(
      "Added ESP32 DevKit. Units received at Lab / Drawer 3:",
    );
  });

  it("checks the stock before asking: a quantity needs a location, a location a quantity", async () => {
    const { user, field } = await openQuickAdd();
    const sent = acceptQuickAdds();
    await user.selectOptions(field.category(), "Boards");
    await user.type(field.name(), "ESP32 DevKit");

    await user.type(field.quantity("Units"), "3{Enter}");

    expect(field.location()).toBeInvalid();
    expect(field.location()).toHaveAccessibleDescription("Stock needs a location to go into.");
    expect(field.location()).toHaveFocus();

    await pickTheDrawer(user, field.location());
    expect(field.location()).toBeValid();
    await user.clear(field.quantity("Units"));
    await user.click(screen.getByRole("button", { name: "Add part" }));

    expect(field.quantity("Units")).toHaveAccessibleDescription(
      /A location needs a quantity to put there\./,
    );
    expect(field.quantity("Units")).toHaveFocus();
    expect(sent).toHaveLength(0);
  });

  it("puts each problem the API finds on the field it names, and focuses the first", async () => {
    const ui = await openQuickAdd();
    refuseQuickAdds([
      aCellProblem({ column: "resistance", code: "invalid", message: "resistance is too big" }),
      aCellProblem({ column: "mpn", code: "invalid", message: "a part number is at most 64" }),
      aCellProblem({ column: "location", code: "unknown_location", message: "no such place" }),
      aCellProblem({ column: "quantity", code: "bad_quantity", message: "out of range" }),
      aCellProblem({ column: "depth", code: "not_an_attribute", message: "'depth' is not one" }),
    ]);
    await fillAResistor(ui);
    await ui.user.type(ui.field.mpn(), "RC0805");
    await ui.user.type(ui.field.quantity(), "25");

    await ui.user.click(screen.getByRole("button", { name: "Add part" }));

    const mpn = ui.field.mpn();
    await expect.poll(() => mpn.getAttribute("aria-invalid")).toBe("true");
    expect(mpn).toHaveAccessibleDescription("Not accepted: a part number is at most 64");
    expect(mpn).toHaveFocus();
    expect(await ui.field.resistance()).toHaveAccessibleDescription(
      /Not accepted: resistance is too big/,
    );
    expect(ui.field.location()).toBeInvalid();
    expect(ui.field.location()).toHaveAccessibleDescription("That location isn't in the tree.");
    expect(ui.field.quantity()).toHaveAccessibleDescription(
      "A quantity is a whole number from 1: up to 1,000,000 of a lot, or 100 units.",
    );
    expect(within(ui.dialog).getByRole("alert")).toHaveTextContent(
      "depth isn't a field of this category.",
    );
  });

  it("links to the part that already holds the part number", async () => {
    const ui = await openQuickAdd();
    refuseQuickAddsAsTaken({ id: PART_ID, name: "10 kΩ 1% 0805" });
    await fillAResistor(ui);
    await ui.user.type(ui.field.quantity(), "5");
    await ui.user.type(ui.field.mpn(), "RC0805FR-0710KL{Enter}");

    const link = await within(ui.dialog).findByRole("link", { name: "Open 10 kΩ 1% 0805" });
    expect(link).toHaveAttribute("href", `/parts/${PART_ID}`);
    expect(ui.field.mpn()).toBeInvalid();
    expect(ui.field.mpn()).toHaveAccessibleDescription(
      "10 kΩ 1% 0805 already has this manufacturer and part number.",
    );
    expect(ui.field.mpn()).toHaveFocus();

    await ui.user.click(link);
    expect(screen.queryByRole("dialog", { name: "Quick add" })).toBeNull();
  });

  it("says a refusal that names no field above the buttons", async () => {
    const ui = await openQuickAdd();
    refuseQuickAddsWith("the part to copy from doesn't exist");
    await fillAResistor(ui);
    await ui.user.type(ui.field.quantity(), "1{Enter}");

    expect(await within(ui.dialog).findByRole("alert")).toHaveTextContent(
      "the part to copy from doesn't exist",
    );
  });

  it("adds another with the category, manufacturer, package and location kept", async () => {
    const ui = await openQuickAdd();
    const sent = acceptQuickAdds(aQuickAddResponse({ part_id: PART_ID }));
    await fillAResistor(ui);
    await ui.user.type(ui.field.mpn(), "RC0805FR-074K7L");
    await ui.user.type(ui.field.manufacturer(), "Yageo");
    await ui.user.type(ui.field.package(), "0805");
    await ui.user.type(ui.field.quantity(), "25{Enter}");
    const another = await within(ui.dialog).findByRole("button", { name: "Add another" });
    await expect.poll(() => document.activeElement).toBe(another);

    // Enter again: Add another is focused, so a bag of parts is typed without the mouse.
    await ui.user.keyboard("{Enter}");

    const name = await within(ui.dialog).findByRole("textbox", { name: "Name" });
    expect(name).toHaveFocus();
    expect(name).toHaveValue("");
    expect(ui.field.category()).toHaveValue(resistors.id);
    expect(ui.field.manufacturer()).toHaveValue("Yageo");
    expect(ui.field.package()).toHaveValue("0805");
    expect(ui.field.mpn()).toHaveValue("");
    expect(await ui.field.resistance()).toHaveValue("");
    expect(ui.field.quantity()).toHaveValue(null);
    expect(await within(ui.dialog).findByDisplayValue("Lab / Drawer 3")).toBe(ui.field.location());

    await ui.user.type(await ui.field.resistance(), "10k");
    await ui.user.type(name, "10 kΩ 1% 0805");
    await ui.user.type(ui.field.quantity(), "10{Enter}");

    await expect.poll(() => sent.length).toBe(2);
    expect(sent[1]).toEqual({
      part: {
        category_id: resistors.id,
        name: "10 kΩ 1% 0805",
        manufacturer: "Yageo",
        mpn: null,
        package: "0805",
        attributes: { resistance: "10k" },
      },
      stock: { location_id: drawer.id, quantity: 10 },
    });
  });

  it("shuts the location list with the first Escape and the dialog with the second", async () => {
    const { user, field } = await openQuickAdd();

    await user.type(field.location(), "lab");
    await screen.findByRole("option", { name: /Drawer 3/ });
    await user.keyboard("{Escape}");

    expect(screen.getByRole("dialog", { name: "Quick add" })).toBeInTheDocument();
    expect(screen.queryByRole("listbox")).toBeNull();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Quick add" })).toBeNull();
    expect(screen.getByRole("button", { name: "Open quick add" })).toHaveFocus();
  });
});

describe("duplicating a part", () => {
  const title = "Duplicate 10 kΩ 1% 0805";

  it("starts from the source, name selected, and copies its pinout on save", async () => {
    const ui = await openQuickAdd({ duplicateOf: { ...tenK, pin_count: 8 } }, title);
    const sent = acceptQuickAdds(aQuickAddResponse({ part_id: PART_ID, name: "4.7 kΩ 1% 0805" }));

    const name = ui.field.name();
    await expect.poll(() => document.activeElement).toBe(name);
    expect(name).toHaveValue("10 kΩ 1% 0805");
    expect(name).toHaveProperty("selectionStart", 0);
    expect(name).toHaveProperty("selectionEnd", "10 kΩ 1% 0805".length);
    expect(ui.field.category()).toHaveValue(resistors.id);
    expect(ui.field.manufacturer()).toHaveValue("Yageo");
    expect(ui.field.package()).toHaveValue("0805");
    expect(ui.field.mpn()).toHaveValue("");
    // As the part page shows it, in engineering notation, not as the stored zeros.
    const resistanceField = await ui.field.resistance();
    expect(resistanceField).toHaveValue("10k");

    // The name is selected, so typing replaces it.
    await ui.user.keyboard("4.7 kΩ 1% 0805");
    await ui.user.clear(resistanceField);
    await ui.user.type(resistanceField, "4k7");
    await ui.user.type(ui.field.mpn(), "RC0805FR-074K7L{Enter}");

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({
      part: {
        category_id: resistors.id,
        name: "4.7 kΩ 1% 0805",
        manufacturer: "Yageo",
        mpn: "RC0805FR-074K7L",
        package: "0805",
        attributes: { resistance: "4k7" },
      },
      pinout_from: tenK.id,
    });
    expect(ui.dialog).toHaveAccessibleName(title);

    // Add another after a duplicate is a plain quick-add: what a bag has in common is kept,
    // and nothing more of the source, neither its values nor its pinout.
    await ui.user.click(await within(ui.dialog).findByRole("button", { name: "Add another" }));

    expect(ui.dialog).toHaveAccessibleName("Quick add");
    const next = await within(ui.dialog).findByRole("textbox", { name: "Name" });
    expect(next).toHaveFocus();
    expect(next).toHaveValue("");
    expect(ui.field.manufacturer()).toHaveValue("Yageo");
    expect(ui.field.package()).toHaveValue("0805");
    expect(await ui.field.resistance()).toHaveValue("");

    await ui.user.type(await ui.field.resistance(), "2k2");
    await ui.user.type(next, "2.2 kΩ 1% 0805{Enter}");

    await expect.poll(() => sent.length).toBe(2);
    expect(sent[1]).not.toHaveProperty("pinout_from");
  });

  it("asks for no pinout when the source has no pins", async () => {
    const ui = await openQuickAdd({ duplicateOf: tenK }, title);
    const sent = acceptQuickAdds();
    await expect.poll(() => document.activeElement).toBe(ui.field.name());

    await ui.user.keyboard("10 kΩ 5% 0805");
    await ui.user.type(ui.field.mpn(), "RC0805JR-0710KL{Enter}");

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).not.toHaveProperty("pinout_from");
    expect(sent[0]?.part).toMatchObject({
      name: "10 kΩ 5% 0805",
      attributes: { resistance: "10k" },
    });
  });
});

describe("problemText", () => {
  // Typed as every code the API can answer, so a new one fails the typecheck until it is here.
  const EVERY_CODE: Record<ProblemCode, true> = {
    unknown_category: true,
    ambiguous_category: true,
    missing: true,
    invalid: true,
    not_an_attribute: true,
    unknown_location: true,
    ambiguous_location: true,
    location_needed: true,
    quantity_needed: true,
    bad_quantity: true,
    too_many_units: true,
    counted_in_lots: true,
    one_unit_per_label: true,
    bad_serial: true,
    bad_mac: true,
    serial_taken: true,
    mac_taken: true,
    extra_cells: true,
    sheet_too_many_units: true,
  };
  const codes = Object.keys(EVERY_CODE) as ProblemCode[];

  it.each(["en", "pt-BR"] as const)("has a sentence for every code in %s", (language) => {
    const t = createI18n(language).getFixedT(language);
    for (const code of codes) {
      const text = problemText(aCellProblem({ column: "depth", code, message: "why" }), t);
      expect(text, code).not.toContain("inventory.intake");
      expect(text, code).not.toContain("{{");
      expect(text.length, code).toBeGreaterThan(3);
    }
  });

  it("carries the server's sentence as the detail of a refused value", () => {
    const t = createI18n("pt-BR").getFixedT("pt-BR");
    const problem = aCellProblem({ column: "resistance", code: "invalid", message: "too big" });

    expect(problemText(problem, t)).toBe("Não aceito: too big");
  });
});
