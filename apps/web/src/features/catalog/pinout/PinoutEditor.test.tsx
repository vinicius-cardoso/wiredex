import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PartDetails } from "@wiredex/api-client";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { renderInRouter } from "../../../test/render";
import {
  acceptPinoutSaves,
  aPartDetails,
  aPin,
  refusePinoutSaves,
  respondWithPinout,
  server,
} from "../../../test/server";
import { PinoutEditor } from "./PinoutEditor";

/** Two pins of an AMS1117-3.3, the second one on the 3.3 V rail it regulates. */
const PINS = [
  aPin({ number: "1", label: "GND", type: "ground" }),
  aPin({ number: "2", label: "VOUT", type: "power", voltage: { value: "3.3", display: "3.3V" } }),
];

const regulator = aPartDetails({ name: "AMS1117-3.3", pin_count: PINS.length });

/** A part with no pinout at all: nothing is fetched, so no handler is needed for it. */
const blank = aPartDetails({ id: "0199cccc-0000-7000-8000-0000000000ff", pin_count: 0 });

function renderEditor(part: PartDetails = regulator) {
  const onClose = vi.fn();
  const { router } = renderInRouter(<PinoutEditor part={part} onClose={onClose} />);
  return Object.assign(onClose, { router });
}

/** The rows being edited, without the header one. */
async function rows() {
  const table = await screen.findByRole("table", { name: "Pins being edited" });
  return within(table).getAllByRole("row").slice(1);
}

function numberOf(row: number) {
  return screen.getByRole("textbox", { name: `Pin ${row}, number` });
}

function labelOf(row: number) {
  return screen.getByRole("textbox", { name: `Pin ${row}, label` });
}

function typeOf(row: number) {
  return screen.getByRole("combobox", { name: `Pin ${row}, type` });
}

function save() {
  return screen.getByRole("button", { name: "Save the pinout" });
}

/** Opens the paste box and pastes `text` into it, as a spreadsheet copy arrives. */
async function paste(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.click(screen.getByRole("button", { name: "Paste a table" }));
  const box = await screen.findByRole("textbox", { name: "Pasted table" });
  await user.click(box);
  await user.paste(text);
}

describe("PinoutEditor", () => {
  it("starts from the pins that are stored", async () => {
    respondWithPinout(regulator.id, PINS);
    renderEditor();

    expect(await rows()).toHaveLength(2);
    expect(numberOf(1)).toHaveValue("1");
    expect(labelOf(1)).toHaveValue("GND");
    expect(typeOf(2)).toHaveValue("power");
    // The exact value, not `3.3V`: saving the row again stores the volts it already had.
    expect(screen.getByRole("textbox", { name: "Pin 2, voltage" })).toHaveValue("3.3");
  });

  it("sends the whole table, with the cell that was retyped", async () => {
    respondWithPinout(regulator.id, PINS);
    const sent = acceptPinoutSaves(PINS);
    const onClose = renderEditor();
    await rows();
    const user = userEvent.setup();

    await user.clear(labelOf(2));
    await user.type(labelOf(2), "VO");
    await user.click(save());

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]?.pins).toEqual([
      { number: "1", label: "GND", type: "ground", functions: [], voltage: null },
      { number: "2", label: "VO", type: "power", functions: [], voltage: "3.3" },
    ]);
    await expect.poll(() => onClose.mock.calls.length).toBe(1);
  });

  it("adds a row and removes it again", async () => {
    renderEditor(blank);
    const user = userEvent.setup();

    expect(await screen.findByText("No pins yet. Add one, or paste a table.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add a pin" }));
    await user.type(numberOf(1), "EP");
    await user.type(labelOf(1), "PAD");
    expect(numberOf(1)).toHaveValue("EP");

    await user.click(screen.getByRole("button", { name: "Remove pin 1" }));
    expect(screen.getByText("No pins yet. Add one, or paste a table.")).toBeInTheDocument();
  });

  it("clears the pinout when every row is gone", async () => {
    respondWithPinout(regulator.id, PINS);
    const sent = acceptPinoutSaves([]);
    renderEditor();
    await rows();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Remove pin 1" }));
    await user.click(screen.getByRole("button", { name: "Remove pin 1" }));
    await user.click(save());

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]?.pins).toEqual([]);
  });

  it("moves a row, cells and all, and stops at the ends", async () => {
    respondWithPinout(regulator.id, PINS);
    renderEditor();
    await rows();
    const user = userEvent.setup();

    expect(screen.getByRole("button", { name: "Move pin 1 up" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move pin 2 down" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Move pin 1 down" }));

    // The names follow the row, not the pin: what was row 1 is now row 2.
    expect(labelOf(1)).toHaveValue("VOUT");
    expect(labelOf(2)).toHaveValue("GND");

    await user.click(screen.getByRole("button", { name: "Move pin 2 up" }));
    expect(labelOf(1)).toHaveValue("GND");
  });

  it("replaces the table with a pasted one, header and all", async () => {
    respondWithPinout(regulator.id, PINS);
    renderEditor();
    await rows();
    const user = userEvent.setup();

    await paste(
      user,
      "Pin\tName\tType\tFunctions\tVoltage\n1\tGND\tGND\n3\tSDI\tI/O\tSDA/MOSI\t3V3",
    );

    const preview = screen.getByRole("table", { name: "Pasted pins" });
    expect(within(preview).getAllByRole("row").slice(1)).toHaveLength(2);
    expect(screen.getByText("Lines read: 2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Replace the table" }));

    expect(await rows()).toHaveLength(2);
    expect(numberOf(2)).toHaveValue("3");
    expect(typeOf(2)).toHaveValue("io");
    expect(screen.getByRole("textbox", { name: "Pin 2, alternate functions" })).toHaveValue(
      "SDA MOSI",
    );
    expect(screen.getByRole("textbox", { name: "Pin 2, voltage" })).toHaveValue("3V3");
    expect(screen.queryByRole("table", { name: "Pasted pins" })).toBeNull();
  });

  it("adds a pasted table to the rows already there", async () => {
    respondWithPinout(regulator.id, PINS);
    renderEditor();
    await rows();
    const user = userEvent.setup();

    await paste(user, "3;VIN;power");
    await user.click(screen.getByRole("button", { name: "Add to the table" }));

    expect(await rows()).toHaveLength(3);
    expect(labelOf(1)).toHaveValue("GND");
    expect(labelOf(3)).toHaveValue("VIN");
  });

  it("says what it had to interpret, and keeps a type it doesn't know", async () => {
    renderEditor(blank);
    const user = userEvent.setup();
    await screen.findByText("No pins yet. Add one, or paste a table.");

    await user.click(screen.getByRole("button", { name: "Paste a table" }));
    expect(screen.getByText("Nothing pasted yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace the table" })).toBeDisabled();

    const box = screen.getByRole("textbox", { name: "Pasted table" });
    await user.click(box);
    await user.paste("1;VCC\n2;XTAL;clock");

    const preview = screen.getByRole("table", { name: "Pasted pins" });
    expect(preview).toHaveTextContent("Type guessed from the label.");
    expect(preview).toHaveTextContent("Type kept as pasted: it is none of the eight.");

    await user.click(screen.getByRole("button", { name: "Replace the table" }));

    // The guess landed, and the spelling nobody knows is still there to be picked over.
    expect(typeOf(1)).toHaveValue("power");
    expect(typeOf(2)).toHaveValue("clock");
  });

  it("leaves a short pasted row as short as it came", async () => {
    renderEditor(blank);
    const user = userEvent.setup();
    await screen.findByText("No pins yet. Add one, or paste a table.");

    await paste(user, "7;CSB");

    const preview = screen.getByRole("table", { name: "Pasted pins" });
    const [only] = within(preview).getAllByRole("row").slice(1);
    const cells = within(only as HTMLElement).getAllByRole("cell");
    expect(cells.map((column) => column.textContent)).toEqual(["7", "CSB", "—", "—", "—", ""]);

    await user.click(screen.getByRole("button", { name: "Add to the table" }));

    // Nothing was made up for the missing type: the select asks for one.
    expect(typeOf(1)).toHaveValue("");
    expect(within(typeOf(1)).getByRole("option", { name: "Pick a type" })).toBeInTheDocument();
  });

  it("closes the paste box without touching the table", async () => {
    respondWithPinout(regulator.id, PINS);
    renderEditor();
    await rows();
    const user = userEvent.setup();

    await paste(user, "9;NC;nc");
    await user.click(screen.getByRole("button", { name: "Cancel the paste" }));

    expect(screen.queryByRole("textbox", { name: "Pasted table" })).toBeNull();
    expect(await rows()).toHaveLength(2);
  });

  it("marks the cell a refused save names, keeping every edit", async () => {
    respondWithPinout(regulator.id, PINS);
    refusePinoutSaves("row 2: pin 1 is already row 1", { row: 2, field: "number" });
    const onClose = renderEditor();
    await rows();
    const user = userEvent.setup();

    await user.clear(numberOf(2));
    await user.type(numberOf(2), "1");
    await user.click(save());

    await expect.poll(() => numberOf(2).getAttribute("aria-invalid")).toBe("true");
    expect(numberOf(2)).toHaveAccessibleDescription("row 2: pin 1 is already row 1");
    // What was typed is still there, and the keyboard is on the cell to fix.
    expect(numberOf(2)).toHaveValue("1");
    expect(numberOf(2)).toHaveFocus();
    expect(numberOf(1)).not.toHaveAttribute("aria-invalid");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("marks the type cell when the refusal is about the type", async () => {
    respondWithPinout(regulator.id, PINS);
    refusePinoutSaves("row 1: 'clock' is not a pin type", { row: 1, field: "type" });
    renderEditor();
    await rows();
    const user = userEvent.setup();

    await user.click(save());

    await expect.poll(() => typeOf(1).getAttribute("aria-invalid")).toBe("true");
    expect(typeOf(1)).toHaveFocus();
  });

  it("shows a refusal of the whole table without marking a cell", async () => {
    respondWithPinout(regulator.id, PINS);
    refusePinoutSaves("a pinout has at most 1024 pins");
    renderEditor();
    await rows();
    const user = userEvent.setup();

    await user.click(save());

    expect(await screen.findByRole("alert")).toHaveTextContent("at most 1024 pins");
    expect(numberOf(1)).not.toHaveAttribute("aria-invalid");
  });

  it("asks before discarding what was typed", async () => {
    respondWithPinout(regulator.id, PINS);
    const onClose = renderEditor();
    await rows();
    const user = userEvent.setup();

    await user.type(labelOf(1), "X");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    const question = screen.getByRole("group", { name: "Discard the changes to this pinout?" });
    await user.click(within(question).getByRole("button", { name: "Keep editing" }));

    expect(onClose).not.toHaveBeenCalled();
    expect(labelOf(1)).toHaveValue("GNDX");

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Discard changes" }));

    expect(onClose).toHaveBeenCalled();
  });

  it("closes straight away when nothing was touched", async () => {
    respondWithPinout(regulator.id, PINS);
    const onClose = renderEditor();
    await rows();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onClose).toHaveBeenCalled();
    expect(screen.queryByRole("group")).toBeNull();
  });

  it("says so when the stored pinout can't be loaded", async () => {
    // Nothing is editable before the stored rows are in: replacing a table nobody could
    // read would save an empty pinout over a full one.
    server.use(http.get("*/api/catalog/parts/:partId/pinout", () => HttpResponse.error()));
    renderEditor();

    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't be loaded");
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("leaving the editor by navigating away", () => {
  it("asks first when there are unsaved edits, and stays when told to", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    respondWithPinout(regulator.id, PINS);
    const { router } = renderEditor();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Pin 1, label"), "X");

    router.history.push("/elsewhere");

    await expect.poll(() => confirm.mock.calls.length).toBe(1);
    expect(screen.queryByText("Elsewhere")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Pin 1, label")).toBeInTheDocument();
    confirm.mockRestore();
  });

  it("leaves without asking when nothing changed", async () => {
    const confirm = vi.spyOn(window, "confirm");
    respondWithPinout(regulator.id, PINS);
    const { router } = renderEditor();
    await screen.findByLabelText("Pin 1, label");

    router.history.push("/elsewhere");

    expect(await screen.findByText("Elsewhere")).toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
    confirm.mockRestore();
  });
});
