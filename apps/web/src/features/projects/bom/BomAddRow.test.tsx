import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Bom } from "@wiredex/api-client";
import { delay, http } from "msw";
import { describe, expect, it } from "vitest";
import { renderInRouter } from "../../../test/render";
import {
  aBom,
  aBomLine,
  aBomPart,
  aBomPartFacts,
  acceptBomWrites,
  aPart,
  aRevision,
  refuseBomWrites,
  respondWithPartSuggestions,
  server,
} from "../../../test/server";
import { BomSection } from "./BomSection";

const resistor = aPart();
const sensor = aPart({
  id: "0199cccc-0000-7000-8000-0000000000d2",
  name: "BME280",
  manufacturer: "Bosch",
  mpn: "BME280",
});
const wire = aPart({
  id: "0199cccc-0000-7000-8000-0000000000d3",
  name: "Hook-up wire 22 AWG",
  manufacturer: null,
  mpn: null,
  package: null,
});
const resistorFacts = aBomPart({ available: 3 });
const catalog = [
  resistorFacts,
  aBomPart({ part_id: sensor.id, available: 0, part: aBomPartFacts({ name: sensor.name }) }),
  aBomPart({
    part_id: wire.id,
    available: null,
    part: aBomPartFacts({ name: wire.name, not_stocked: true }),
  }),
];

const empty = aBom({ lines: [], parts: [] });

async function renderEditor(initial: Bom = empty) {
  const writes = acceptBomWrites(initial, catalog);
  respondWithPartSuggestions([resistor, sensor, wire]);
  renderInRouter(<BomSection revision={aRevision()} />);
  const row = await screen.findByRole("row", { name: "New line" });
  const inside = within(row);
  const field = {
    designators: inside.getByRole("textbox", { name: "Designators" }),
    part: inside.getByRole("combobox", { name: "Part" }),
    quantity: inside.getByRole("spinbutton", { name: "Quantity" }),
    notes: inside.getByRole("textbox", { name: "Notes" }),
  };
  return { writes, row, field, user: userEvent.setup() };
}

type Ui = Awaited<ReturnType<typeof renderEditor>>;

/** Types into the part box and picks the part named, with the arrows and Enter. */
async function pickPart({ user, field }: Ui, typed: string, name: RegExp) {
  await user.type(field.part, typed);
  const option = await screen.findByRole("option", { name });
  while (field.part.getAttribute("aria-activedescendant") !== option.id) {
    await user.keyboard("{ArrowDown}");
  }
  await user.keyboard("{Enter}");
}

function linesTable() {
  return screen.getByRole("table", { name: "Lines of the bill of materials" });
}

describe("BomAddRow", () => {
  it("adds a line typed as designators, Tab, part, Enter, Enter, and is ready for the next", async () => {
    const ui = await renderEditor();
    const { user, field, writes } = ui;

    await user.click(field.designators);
    await user.keyboard("r1-4");
    await user.tab();
    expect(field.part).toHaveFocus();
    await pickPart(ui, "4.7", /4.7 kΩ/);
    expect(field.part).toHaveValue(resistor.name);
    await user.keyboard("{Enter}");

    await waitFor(() => expect(field.designators).toHaveFocus());
    expect(writes.additions).toEqual([
      { part_id: resistor.id, designators: "r1-4", quantity: null, notes: "" },
    ]);
    expect(field.designators).toHaveValue("");
    expect(field.part).toHaveValue("");
    expect(within(linesTable()).getByRole("row", { name: /R1–R4/ })).toHaveTextContent("Short");
    expect(screen.getByRole("region", { name: "Shortages" })).toHaveTextContent("Pieces short1");
  });

  it("keeps what is typed for the next line while the first is still on its way", async () => {
    const ui = await renderEditor();
    const { user, field, writes } = ui;

    // The save takes a moment, as it does over a network; it then falls through to the fake.
    server.use(
      http.post("*/api/projects/revisions/:revisionId/bom/lines", async () => {
        await delay(150);
      }),
    );

    await user.click(field.designators);
    await user.keyboard("r1-4");
    await pickPart(ui, "4.7", /4.7 kΩ/);
    await user.keyboard("{Enter}");
    // Straight on to the next line, without waiting for the table to show the first.
    await user.keyboard("c1");

    await waitFor(() => expect(writes.additions).toHaveLength(1));
    expect(await within(linesTable()).findByRole("row", { name: /R1–R4/ })).toBeInTheDocument();
    // The row cleared when the line was sent, so the answer and the refresh wiped nothing.
    expect(field.designators).toHaveValue("c1");
    expect(field.designators).toHaveFocus();
  });

  it("puts a refused line back in the row", async () => {
    const ui = await renderEditor();
    const { user, field } = ui;
    refuseBomWrites("boom", 500);

    await user.click(field.designators);
    await user.keyboard("r1-4");
    await pickPart(ui, "4.7", /4.7 kΩ/);
    await user.keyboard("{Enter}");

    await waitFor(() => expect(field.designators).toHaveValue("r1-4"));
    expect(field.part).toHaveValue(resistor.name);
    expect(within(linesTable()).queryByRole("row", { name: /R1–R4/ })).not.toBeInTheDocument();
  });

  it("previews the designators as they will be stored, their count the read-only quantity", async () => {
    const { user, field } = await renderEditor();

    await user.type(field.designators, "r7 r1-4");

    expect(field.designators).toHaveAccessibleDescription("Reads as R1–R4, R7; quantity 5.");
    expect(field.quantity).toHaveValue(5);
    expect(field.quantity).toHaveAttribute("readonly");
    expect(field.quantity).toHaveAccessibleDescription("The number of designators.");

    await user.type(field.designators, ", R0");
    expect(field.designators).toHaveAccessibleDescription(
      "R0 isn't a designator like R1 or C12: 1 to 8 letters, then a number from 1 to 9,999.",
    );

    await user.clear(field.designators);
    expect(field.quantity).not.toHaveAttribute("readonly");
    expect(field.quantity).toHaveValue(null);
  });

  it.each(["designators", "part", "quantity", "notes"] as const)(
    "adds a line with Enter from %s",
    async (from) => {
      const ui = await renderEditor();
      const { user, field, writes } = ui;

      await user.click(field.part);
      await pickPart(ui, "wire", /Hook-up wire/);
      await user.type(field.quantity, "1");
      await user.type(field.notes, "2 m");
      await user.click(field[from]);
      await user.keyboard("{Enter}");

      await waitFor(() => expect(writes.additions).toHaveLength(1));
      expect(writes.additions[0]).toEqual({
        part_id: wire.id,
        designators: "",
        quantity: 1,
        notes: "2 m",
      });
      expect(await within(linesTable()).findByText("Not stocked")).toBeInTheDocument();
    },
  );

  it("names the line holding a designator already taken, on Designators", async () => {
    const ui = await renderEditor(aBom({ lines: [aBomLine()], parts: [resistorFacts] }));
    const { user, field } = ui;

    await user.type(field.designators, "R4");
    await user.tab();
    await pickPart(ui, "bosch", /BME280/);
    await user.keyboard("{Enter}");

    await waitFor(() => expect(field.designators).toHaveAttribute("aria-invalid", "true"));
    expect(field.designators).toHaveFocus();
    expect(field.designators).toHaveAccessibleDescription(
      "Reads as R4; quantity 1. R4 is already on the line R1–R4.",
    );
    // Typing again drops the refusal.
    await user.type(field.designators, "0");
    expect(field.designators).not.toHaveAttribute("aria-invalid");
  });

  it("asks for a part before sending anything", async () => {
    const { user, field, writes } = await renderEditor();

    await user.type(field.designators, "U1{Enter}");

    expect(field.part).toHaveFocus();
    expect(field.part).toHaveAttribute("aria-invalid", "true");
    expect(field.part).toHaveAccessibleDescription("Pick a part from the catalog.");
    expect(writes.additions).toEqual([]);
  });

  it("puts a refused quantity and refused notes on their fields", async () => {
    const ui = await renderEditor();
    const { user, field } = ui;

    await pickPart(ui, "bosch", /BME280/);
    await user.click(field.notes);
    await user.paste("x".repeat(501));
    await user.keyboard("{Enter}");
    await waitFor(() => expect(field.quantity).toHaveFocus());
    expect(field.quantity).toHaveAccessibleDescription("Give a whole number from 1 to 10,000.");

    await user.type(field.quantity, "2{Enter}");
    await waitFor(() => expect(field.notes).toHaveFocus());
    expect(field.notes).toHaveAttribute("aria-invalid", "true");
    expect(field.notes).toHaveAccessibleDescription("Notes hold at most 500 characters.");
  });

  it("puts FastAPI's own refusal on the field it names, in the server's words", async () => {
    const ui = await renderEditor();
    refuseBomWrites(
      [{ loc: ["body", "designators"], msg: "String should have at most 4000 characters" }],
      422,
    );

    await ui.user.type(ui.field.designators, "U1");
    await ui.user.tab();
    await pickPart(ui, "bosch", /BME280/);
    await ui.user.keyboard("{Enter}");

    await waitFor(() =>
      expect(ui.field.designators).toHaveAccessibleDescription(
        "Reads as U1; quantity 1. String should have at most 4000 characters",
      ),
    );
  });

  it("says on the row why a refusal that names no field was refused, in Portuguese too", async () => {
    const writes = acceptBomWrites(empty, catalog);
    respondWithPartSuggestions([resistor, sensor, wire]);
    refuseBomWrites(
      {
        message: "revision A is reserved; only a draft's content can change",
        code: "revision_locked",
        field: null,
        item: null,
        line_id: null,
        line: null,
      },
      409,
    );
    renderInRouter(<BomSection revision={aRevision()} />, { language: "pt-BR" });
    const row = await screen.findByRole("row", { name: "Nova linha" });
    const user = userEvent.setup();
    const part = within(row).getByRole("combobox", { name: "Peça" });

    await user.type(part, "bosch");
    await screen.findByRole("option", { name: /BME280/ });
    await user.keyboard("{ArrowDown}{Enter}");
    await user.type(within(row).getByRole("textbox", { name: "Designadores" }), "U1{Enter}");

    expect(await within(row).findByRole("alert")).toHaveTextContent(
      "Só a lista de materiais de um rascunho pode mudar.",
    );
    expect(writes.additions).toEqual([]);
  });
});
