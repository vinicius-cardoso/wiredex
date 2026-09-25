import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PartDetails } from "@wiredex/api-client";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../../test/render";
import { aPartDetails, aPin, respondWithPinout, server } from "../../../test/server";
import { PinoutSection } from "./PinoutSection";

const LEVEL = { value: "3.3", display: "3.3V" };

/** Four pins of a BME280, `SDI` carrying `SDA` among its alternate functions. */
const PINS = [
  aPin({ number: "1", label: "GND", type: "ground" }),
  aPin({ number: "3", label: "SDI", type: "io", functions: ["SDA", "MOSI"], voltage: LEVEL }),
  aPin({ number: "4", label: "SCK", type: "io", functions: ["SCL"], voltage: LEVEL }),
  aPin({ number: "8", label: "VDD", type: "power", voltage: LEVEL }),
];

const sensor = aPartDetails({ name: "BME280", pin_count: PINS.length });

function renderSection(part: PartDetails = sensor, onEdit = vi.fn()) {
  renderWithProviders(<PinoutSection part={part} onEdit={onEdit} />);
  return onEdit;
}

/** The pins, without the header row. */
async function pinRows() {
  const rows = within(await screen.findByRole("table")).getAllByRole("row");
  return rows.slice(1);
}

describe("PinoutSection", () => {
  it("shows one row per pin, in the order they were saved", async () => {
    respondWithPinout(sensor.id, PINS);
    renderSection();

    const rows = await pinRows();

    const numbers = rows.map((row) => within(row).getAllByRole("cell")[0]?.textContent);
    expect(numbers).toEqual(["1", "3", "4", "8"]);
    // The pin as a datasheet gives it: number, label, type, functions, level.
    const sdi = within(rows[1] as HTMLElement).getAllByRole("cell");
    expect(sdi.map((cell) => cell.textContent)).toEqual(["3", "SDI", "I/O", "SDA MOSI", "3.3V"]);
    expect(screen.getByRole("button", { name: "Edit pinout" })).toBeInTheDocument();
  });

  it("narrows the rows by an alternate function, not only the label", async () => {
    respondWithPinout(sensor.id, PINS);
    renderSection();
    await pinRows();
    const user = userEvent.setup();

    await user.type(screen.getByRole("searchbox", { name: "Filter pins" }), "sda");

    const rows = await pinRows();
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("SDI");
  });

  it("says when nothing matches the filter", async () => {
    respondWithPinout(sensor.id, PINS);
    renderSection();
    await pinRows();
    const user = userEvent.setup();

    await user.type(screen.getByRole("searchbox", { name: "Filter pins" }), "GPIO21");

    expect(await screen.findByText("No pin matches that filter.")).toBeInTheDocument();
    expect(await pinRows()).toHaveLength(0);
  });

  it("offers to add one for a part that has no pinout", async () => {
    // No handler for the pinout: a part whose `pin_count` is 0 is answered from the part
    // itself, and an unhandled request would fail this test.
    const onEdit = renderSection(aPartDetails({ pin_count: 0 }));
    const user = userEvent.setup();

    expect(await screen.findByText("No pinout yet.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Add a pinout" }));
    expect(onEdit).toHaveBeenCalled();
  });

  it("says so when the pinout can't be loaded", async () => {
    server.use(http.get("*/api/catalog/parts/:partId/pinout", () => HttpResponse.error()));
    renderSection();

    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't be loaded");
  });
});
