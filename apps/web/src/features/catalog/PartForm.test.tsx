import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aCategory,
  acceptPartSaves,
  anAttribute,
  aPartDetails,
  refusePartSaves,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithCategories,
  respondWithCategorySchema,
  respondWithPart,
} from "../../test/server";

const resistors = aCategory({ name: "Resistors" });

const resistance = anAttribute({ key: "resistance", label: "Resistance", unit: "Ω" });
const tolerance = anAttribute({
  id: "0199dddd-0000-7000-8000-000000000002",
  key: "tolerance",
  label: "Tolerance",
  kind: "enum",
  unit: null,
  required: false,
  options: ["1%", "5%"],
  position: 1,
});
const note = anAttribute({
  id: "0199dddd-0000-7000-8000-000000000003",
  key: "note",
  label: "Note",
  kind: "text",
  unit: null,
  required: false,
  position: 2,
});
const pulled = anAttribute({
  id: "0199dddd-0000-7000-8000-000000000004",
  key: "pulled",
  label: "Pulled from a board",
  kind: "bool",
  unit: null,
  required: false,
  position: 3,
});

function renderNewPartPage(attributes = [resistance, tolerance, note, pulled]) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  respondWithCategories([resistors]);
  respondWithCategorySchema(resistors, attributes);
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: ["/parts/new"] });
  renderWithProviders(<RouterProvider router={createAppRouter(queryClient, history)} />, {
    queryClient,
  });
}

/** Picking the category is what fetches the schema, so every test starts there. */
async function pickTheCategory(user: ReturnType<typeof userEvent.setup>) {
  const choice = await screen.findByRole("combobox", { name: "Category" });
  await user.selectOptions(choice, await screen.findByRole("option", { name: "Resistors" }));
  return await screen.findByRole("textbox", { name: "Resistance" });
}

describe("PartForm", () => {
  it("renders one field per kind once a category is picked", async () => {
    renderNewPartPage();
    const user = userEvent.setup();

    await pickTheCategory(user);

    expect(screen.getByRole("textbox", { name: "Resistance" })).toHaveAccessibleDescription("Ω");
    expect(screen.getByRole("combobox", { name: "Tolerance" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "5%" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Note" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Pulled from a board" })).toBeInTheDocument();
  });

  it("shows what a number normalizes to without rewriting what was typed", async () => {
    renderNewPartPage();
    const user = userEvent.setup();
    const field = await pickTheCategory(user);

    await user.type(field, "4k7");

    expect(field).toHaveValue("4k7");
    expect(await screen.findByText("= 4.7kΩ")).toBeInTheDocument();

    await user.clear(field);
    await user.type(field, "100");

    expect(field).toHaveValue("100");
    expect(screen.getByText("= 100Ω")).toBeInTheDocument();
  });

  it("marks a required field and sends nothing until it is filled in", async () => {
    renderNewPartPage();
    const user = userEvent.setup();
    const field = await pickTheCategory(user);
    // No handler for POST /parts: a request would fail the test as unhandled.
    await user.type(screen.getByRole("textbox", { name: "Name" }), "Resistor");

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("This one is needed.")).toBeInTheDocument();
    expect(field).toBeInvalid();

    const sent = acceptPartSaves();
    await user.type(field, "4k7");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]?.attributes).toEqual({ resistance: "4k7", pulled: false });
    expect(sent[0]?.name).toBe("Resistor");
  });

  it("refuses a number it can't read, before asking the API", async () => {
    renderNewPartPage();
    const user = userEvent.setup();
    const field = await pickTheCategory(user);

    await user.type(screen.getByRole("textbox", { name: "Name" }), "Resistor");
    await user.type(field, "10K");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText(/Not a number/)).toBeInTheDocument();
  });

  it("puts the API's refusal on the field it names", async () => {
    renderNewPartPage();
    refusePartSaves("resistance takes a number, not text");
    const user = userEvent.setup();
    const field = await pickTheCategory(user);

    await user.type(screen.getByRole("textbox", { name: "Name" }), "Resistor");
    await user.type(field, "4k7");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("resistance takes a number, not text")).toBeInTheDocument();
    expect(field).toHaveAccessibleDescription(/takes a number/);
  });

  it("puts a conflicting part number on the part number field", async () => {
    renderNewPartPage([resistance]);
    refusePartSaves("RC0805FR-074K7L is already used by 4.7 kΩ 1% 0805", 409);
    const user = userEvent.setup();
    const field = await pickTheCategory(user);

    await user.type(screen.getByRole("textbox", { name: "Name" }), "Resistor");
    await user.type(field, "4k7");
    await user.type(screen.getByRole("textbox", { name: "Part number" }), "RC0805FR-074K7L");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText(/is already used by/)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Part number" })).toBeInvalid();
  });

  it("opens the part it created", async () => {
    const saved = aPartDetails({ name: "4.7 kΩ 1% 0805", category_id: resistors.id });
    renderNewPartPage([resistance]);
    acceptPartSaves(saved);
    respondWithPart(saved);
    const user = userEvent.setup();
    const field = await pickTheCategory(user);

    await user.type(screen.getByRole("textbox", { name: "Name" }), saved.name);
    await user.type(field, "4k7");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("heading", { level: 1, name: saved.name })).toBeInTheDocument();
  });
});
