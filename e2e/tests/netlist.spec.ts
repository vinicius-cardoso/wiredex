import { expect, type Locator, type Page, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";

/**
 * The netlist end to end (spec 11): a sensor with a pinout and a resistor without one on a
 * revision's BOM, then its wiring typed from the keyboard, the pins combobox offering the
 * designators and then the sensor's pins. A pin whose label is on two pins is refused naming
 * both; a BOM edit leaves a reference marked "not on the BOM", and editing that net's color
 * keeps it; a fork carries the nets; and reserving the revision locks its wiring. On a phone
 * the wiring and its open combobox never scroll the page sideways (10.13).
 *
 * It reuses the session auth.setup.ts saved and never logs out. Every name carries a stamp.
 */

/** Four pins of a sensor as a spreadsheet copies them: GND on two of them. */
const PASTED = [
  "Pin\tName\tType\tFunctions\tVoltage",
  "1\tVDD\tPWR\t\t3V3",
  "2\tGND\tGND",
  "3\tSDI\tI/O\tSDA/MOSI\t3V3",
  "7\tGND\tGND",
].join("\n");

test("wire a revision by keyboard, keep a reference a BOM edit broke, fork and lock it", async ({
  page,
}) => {
  test.slow();
  const info = test.info();
  const stamp = `${info.project.name}-${info.workerIndex}-${Date.now()}`;
  const drawer = `Drawer ${stamp}`;
  const category = `Sensors ${stamp}`;
  const sensor = `Sensor ${stamp}`;
  const resistor = `Resistor ${stamp}`;
  const station = `Station ${stamp}`;

  await page.goto("/locations");
  await page.getByLabel("Add a location").fill(drawer);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name: drawer })).toBeVisible();

  await page.goto("/categories");
  await page.getByLabel("Add a category").fill(category);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name: category })).toBeVisible();

  // The sensor with its pinout, one of it received; the resistor with none, two received.
  await createPart(page, category, sensor);
  const pinout = page.getByRole("region", { name: "Pinout" });
  await pinout.getByRole("button", { name: "Add a pinout" }).click();
  const editor = page.getByRole("region", { name: "Edit the pinout" });
  await editor.getByRole("button", { name: "Paste a table" }).click();
  await editor.getByRole("textbox", { name: "Pasted table" }).fill(PASTED);
  await editor.getByRole("button", { name: "Replace the table" }).click();
  await editor.getByRole("button", { name: "Save the pinout" }).click();
  await expect(pinout.getByRole("row")).toHaveCount(5);
  await receive(page, drawer, 1);
  await createPart(page, category, resistor);
  await receive(page, drawer, 2);

  // A project whose revision A has the sensor on U1 and the resistor on R1.
  await page.goto("/projects");
  await page.getByRole("link", { name: "New project" }).click();
  await page.getByLabel("Name", { exact: true }).fill(station);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: station })).toBeVisible();
  const revisionA = page.getByRole("region", { name: "Revision A", exact: true });
  const bom = revisionA.getByRole("region", { name: "Bill of materials" });
  await addLine(page, bom, "U1", sensor);
  await addLine(page, bom, "R1", resistor);

  // The wiring: an empty draft offers the row that adds a net (requirement 10.3).
  const wiring = revisionA.getByRole("region", { name: "Wiring" });
  const newNet = wiring.getByRole("row", { name: "New net" });
  const name = newNet.getByRole("textbox", { name: "Net name" });
  const pins = newNet.getByRole("combobox", { name: "Pins" });

  // SDA by keyboard: U picked from the designators, then SDI from U1's pins by its function,
  // written as its number; R1.2 typed, since the resistor has no pinout (10.4, 3.4, 3.7).
  await name.fill("SDA");
  await pins.focus();
  await page.keyboard.type("U");
  await expect(newNet.getByRole("option", { name: /^U1/ })).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(pins).toHaveValue("U1.");
  await page.keyboard.type("sd");
  await expect(newNet.getByRole("option", { name: /^3/ })).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(pins).toHaveValue("U1.3");
  await page.keyboard.type(", R1.2");
  await expectNoSidewaysScroll(page);
  await page.keyboard.press("Enter");

  const nets = wiring.getByRole("table", { name: "Nets of the revision" });
  const sda = nets.getByRole("row", { name: /^SDA/ });
  await expect(sda).toContainText("U1.3");
  await expect(sda).toContainText("SDI");
  await expect(sda).toContainText("not checked: the part has no pinout");
  await expect(name).toBeFocused();

  // GND by label is two pins: refused on Pins, naming both; by number it goes in (3.6, 10.8).
  await name.fill("GND");
  await pins.fill("U1.GND");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Enter");
  await expect(pins).toHaveAttribute("aria-invalid", "true");
  await expect(newNet).toContainText("U1.GND could be pins 2, 7; name one by number.");
  await pins.fill("U1.2");
  await page.keyboard.press("Enter");
  await expect(nets.getByRole("row", { name: /^GND/ })).toContainText("U1.2");

  // R1 renumbered R2 on the BOM: the net keeps R1.2 and marks it (requirement 4.4).
  const lines = bom.getByRole("table", { name: "Lines of the bill of materials" });
  await lines.getByRole("button", { name: /^Edit line R1/ }).click();
  const editingLine = lines.getByRole("row", { name: /^Editing line R1/ });
  await editingLine.getByRole("textbox", { name: "Designators" }).fill("R2");
  await page.keyboard.press("Enter");
  await expect(sda).toContainText("not on the BOM");

  // Editing SDA's color keeps the reference the BOM edit broke (requirement 3.8).
  await nets.getByRole("button", { name: "Edit net SDA" }).click();
  const editingNet = nets.getByRole("row", { name: "Editing net SDA" });
  await editingNet.getByRole("combobox", { name: "Wire color" }).selectOption("blue");
  await editingNet.getByRole("textbox", { name: "Net name" }).press("Enter");
  await expect(sda).toContainText("Blue");
  await expect(sda).toContainText("R1.2");
  await expect(sda).toContainText("not on the BOM");

  // A fork carries both nets (requirement 6.1).
  await revisionA.getByRole("button", { name: "Fork", exact: true }).click();
  const fork = page.getByRole("dialog", { name: "Fork revision A" });
  await fork.getByRole("button", { name: "Fork", exact: true }).click();
  const revisionB = page.getByRole("region", { name: "Revision B", exact: true });
  const netsB = revisionB
    .getByRole("region", { name: "Wiring" })
    .getByRole("table", { name: "Nets of the revision" });
  await expect(netsB.getByRole("row", { name: /^SDA/ })).toContainText("U1.3");
  await expect(netsB.getByRole("row", { name: /^GND/ })).toContainText("U1.2");

  // Reserving A locks its wiring: no new-net row, and a note saying why (5.1, 10.9).
  const addressB = page.url();
  const addressA = await revisionB
    .getByRole("link", { name: "A", exact: true })
    .getAttribute("href");
  if (!addressA) throw new Error("no link from B to the revision it was forked from");
  await page.goto(addressA);
  await revisionA.getByRole("button", { name: "Reserve parts" }).click();
  const reserve = page.getByRole("dialog", { name: "Reserve parts" });
  await reserve.getByRole("button", { name: "Reserve", exact: true }).click();
  await expect(reserve).toBeHidden();
  await expect(wiring.getByText(/Only a draft's wiring can change/)).toBeVisible();
  await expect(wiring.getByRole("row", { name: "New net" })).toHaveCount(0);
  await expect(wiring.getByRole("button", { name: "Edit net SDA" })).toHaveCount(0);
  await expectNoSidewaysScroll(page);
  expect(addressB).not.toEqual(addressA);
});

async function createPart(page: Page, category: string, name: string) {
  await page.goto("/parts");
  await page.getByRole("link", { name: "New part" }).click();
  await page.getByLabel("Category").selectOption({ label: category });
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
}

/** Receives QUANTITY of the part whose page is open into the location named. */
async function receive(page: Page, location: string, quantity: number) {
  const stock = page.getByRole("region", { name: "Stock" });
  await stock.getByRole("button", { name: "Receive" }).click();
  const dialog = page.getByRole("dialog", { name: "Receive stock" });
  const picker = dialog.getByRole("combobox", { name: "Location" });
  const value = await picker
    .getByRole("option", { name: new RegExp(escapeRegExp(location)) })
    .getAttribute("value");
  if (value === null) throw new Error(`no option for the location ${location}`);
  await picker.selectOption(value);
  await dialog.getByRole("spinbutton", { name: "Quantity" }).fill(String(quantity));
  await dialog.getByRole("button", { name: "Receive" }).click();
  await expect(dialog).toBeHidden();
}

/** A BOM line by keyboard: its designators, Tab, the part picked, Enter. */
async function addLine(page: Page, bom: Locator, designators: string, part: string) {
  const newLine = bom.getByRole("row", { name: "New line" });
  await newLine.getByRole("textbox", { name: "Designators" }).fill(designators);
  const picker = newLine.getByRole("combobox", { name: "Part" });
  await picker.focus();
  await page.keyboard.type(part);
  await expect(page.getByRole("option", { name: part })).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(picker).toHaveValue(part);
  await page.keyboard.press("Enter");
  await expect(
    bom.getByRole("table", { name: "Lines of the bill of materials" }).getByText(designators, {
      exact: true,
    }),
  ).toBeVisible();
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
