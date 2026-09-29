import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
} from "../../../test/server";
import { BomSection } from "./BomSection";

const resistor = aBomPart({ available: 3 });
const wire = aBomPart({
  part_id: "0199cccc-0000-7000-8000-0000000000d3",
  available: null,
  part: aBomPartFacts({ name: "Hook-up wire 22 AWG", not_stocked: true }),
});
const pullUps = aBomLine({ notes: "I²C pull-ups" });
const jumpers = aBomLine({
  id: "0199abab-0000-7000-8000-000000000002",
  part_id: wire.part_id,
  designators: [],
  designator_text: "",
  quantity: 1,
  notes: "2 m",
});

async function renderLines() {
  const writes = acceptBomWrites(aBom({ lines: [pullUps, jumpers], parts: [resistor, wire] }));
  respondWithPartSuggestions([aPart()]);
  renderInRouter(<BomSection revision={aRevision()} />);
  const table = await screen.findByRole("table", { name: "Lines of the bill of materials" });
  return { writes, table, user: userEvent.setup() };
}

describe("BomLineRow", () => {
  it("names each line's buttons after its designators, or its part when it has none", async () => {
    const { table } = await renderLines();

    expect(within(table).getByRole("button", { name: "Edit line R1–R4" })).toBeInTheDocument();
    expect(
      within(table).getByRole("button", { name: "Remove line Hook-up wire 22 AWG" }),
    ).toBeInTheDocument();
  });

  it("edits a line in its row and saves it on Enter, focus back on Edit", async () => {
    const { table, user, writes } = await renderLines();

    within(table).getByRole("button", { name: "Edit line R1–R4" }).focus();
    await user.keyboard("{Enter}");
    const row = within(table).getByRole("row", { name: "Editing line R1–R4" });
    const designators = within(row).getByRole("textbox", { name: "Designators" });
    expect(designators).toHaveFocus();
    expect(designators).toHaveValue("R1–R4");
    expect(within(row).getByRole("combobox", { name: "Part" })).toHaveValue(
      resistor.part?.name ?? "",
    );
    expect(within(row).getByRole("spinbutton", { name: "Quantity" })).toHaveValue(4);

    await user.clear(designators);
    await user.keyboard("R1-3{Enter}");

    const edit = await within(table).findByRole("button", { name: "Edit line R1–R3" });
    await waitFor(() => expect(edit).toHaveFocus());
    expect(writes.edits).toEqual([
      {
        lineId: pullUps.id,
        body: {
          part_id: pullUps.part_id,
          designators: "R1-3",
          quantity: null,
          notes: "I²C pull-ups",
        },
      },
    ]);
    // Three needed and three there: the resistor isn't short any more.
    expect(screen.getByText("Nothing is short.")).toBeInTheDocument();
  });

  it("puts the line back as it was on Escape, focus back on Edit, sending nothing", async () => {
    const { table, user, writes } = await renderLines();

    within(table).getByRole("button", { name: "Edit line Hook-up wire 22 AWG" }).focus();
    await user.keyboard("{Enter}");
    const row = within(table).getByRole("row", { name: "Editing line Hook-up wire 22 AWG" });
    const notes = within(row).getByRole("textbox", { name: "Notes" });
    await user.clear(notes);
    await user.type(notes, "3 m{Escape}");

    const edit = within(table).getByRole("button", { name: "Edit line Hook-up wire 22 AWG" });
    expect(edit).toHaveFocus();
    expect(within(table).getByRole("row", { name: /Hook-up wire/ })).toHaveTextContent("2 m");
    expect(writes.edits).toEqual([]);
  });

  it("shows an edit's refusal on its field and keeps the row open", async () => {
    const { table, user } = await renderLines();

    within(table).getByRole("button", { name: "Edit line Hook-up wire 22 AWG" }).focus();
    await user.keyboard("{Enter}");
    const row = within(table).getByRole("row", { name: "Editing line Hook-up wire 22 AWG" });
    const quantity = within(row).getByRole("spinbutton", { name: "Quantity" });
    await user.clear(quantity);
    await user.type(quantity, "0{Enter}");

    await waitFor(() => expect(quantity).toHaveAttribute("aria-invalid", "true"));
    expect(quantity).toHaveAccessibleDescription("Give a whole number from 1 to 10,000.");
    expect(quantity).toHaveFocus();
  });

  it("asks before removing a line, in its row, with focus on Keep", async () => {
    const { table, user, writes } = await renderLines();

    within(table).getByRole("button", { name: "Remove line R1–R4" }).focus();
    await user.keyboard("{Enter}");
    const question = within(table).getByRole("group", { name: "Remove line R1–R4?" });
    expect(question).toHaveTextContent("Remove this line?");
    expect(within(question).getByRole("button", { name: "Keep" })).toHaveFocus();

    // Keep, by Enter on the focused button: nothing sent, focus back on Remove.
    await user.keyboard("{Enter}");
    expect(within(table).getByRole("button", { name: "Remove line R1–R4" })).toHaveFocus();
    expect(writes.removals).toEqual([]);

    await user.keyboard("{Enter}");
    await user.keyboard("{Shift>}{Tab}{/Shift}{Enter}");

    await waitFor(() =>
      expect(within(table).queryByRole("button", { name: "Edit line R1–R4" })).toBeNull(),
    );
    expect(writes.removals).toEqual([pullUps.id]);
  });

  it("keeps the line on Escape while asking, and says when a removal is refused", async () => {
    const { table, user } = await renderLines();

    within(table).getByRole("button", { name: "Remove line R1–R4" }).focus();
    await user.keyboard("{Enter}{Escape}");
    expect(within(table).queryByRole("group")).not.toBeInTheDocument();

    refuseBomWrites({ message: "locked", code: "revision_locked", field: null }, 409);
    within(table).getByRole("button", { name: "Remove line R1–R4" }).focus();
    await user.keyboard("{Enter}{Shift>}{Tab}{/Shift}{Enter}");

    expect(await within(table).findByRole("alert")).toHaveTextContent(
      "Only a draft's bill of materials can change.",
    );
  });
});
