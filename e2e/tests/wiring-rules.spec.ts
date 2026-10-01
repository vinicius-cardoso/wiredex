import { expect, type Locator, type Page, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";

/**
 * The wiring rules end to end (spec 12): a board with a 3.3 V pin, a 5 V pin and two input-only
 * pins, and a resistor without a pinout, on a revision's BOM. A net joining 3.3 V and 5 V is a
 * voltage error naming both levels; a pin in two nets is a reuse error; two inputs wired only to
 * each other are an input-only error, cleared by adding the resistor, whose missing pinout is a
 * warning. Reserving lists the findings as warnings and still reserves. The board's page shows
 * the nets on each pin, and its filter narrows them. On a phone nothing scrolls sideways (10.10).
 *
 * It reuses the session auth.setup.ts saved and never logs out. Every name carries a stamp.
 */

/** The board's pins as a spreadsheet copies them: two inputs with nothing to drive them. */
const PASTED = [
  "Pin\tName\tType\tFunctions\tVoltage",
  "1\t3V3\tPWR\t\t3V3",
  "2\t5V\tPWR\t\t5V",
  "3\tGPIO34\tIN\tADC1_6",
  "4\tCSB\tIN",
  "5\tGND\tGND",
].join("\n");

test("find wiring mistakes, reserve past them, and read a board's pin usage", async ({ page }) => {
  test.slow();
  const info = test.info();
  const stamp = `${info.project.name}-${info.workerIndex}-${Date.now()}`;
  const drawer = `Drawer ${stamp}`;
  const category = `Boards ${stamp}`;
  const board = `Board ${stamp}`;
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

  // The board with its pinout and the resistor with none, one of each received.
  await createPart(page, category, board);
  const boardPage = page.url();
  const pinout = page.getByRole("region", { name: "Pinout" });
  await pinout.getByRole("button", { name: "Add a pinout" }).click();
  const editor = page.getByRole("region", { name: "Edit the pinout" });
  await editor.getByRole("button", { name: "Paste a table" }).click();
  await editor.getByRole("textbox", { name: "Pasted table" }).fill(PASTED);
  await editor.getByRole("button", { name: "Replace the table" }).click();
  await editor.getByRole("button", { name: "Save the pinout" }).click();
  await expect(pinout.getByRole("row")).toHaveCount(6);
  await receive(page, drawer, 1);
  await createPart(page, category, resistor);
  await receive(page, drawer, 1);

  // A project whose revision A has the board on U1 and the resistor on R1.
  await page.goto("/projects");
  await page.getByRole("link", { name: "New project" }).click();
  await page.getByLabel("Name", { exact: true }).fill(station);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: station })).toBeVisible();
  const revisionA = page.getByRole("region", { name: "Revision A", exact: true });
  const bom = revisionA.getByRole("region", { name: "Bill of materials" });
  await addLine(page, bom, "U1", board);
  await addLine(page, bom, "R1", resistor);

  const wiring = revisionA.getByRole("region", { name: "Wiring", exact: true });
  const nets = wiring.getByRole("table", { name: "Nets of the revision" });
  const checks = wiring.getByRole("region", { name: "Wiring checks" });

  // 3.3 V and 5 V on one net: a voltage error naming both levels (requirement 4.1).
  await addNet(page, wiring, "VCC", "U1.1, U1.2");
  await expect(checks).toContainText("A net joins 3.3 V and 5 V pins.");
  await expect(checks.getByRole("link", { name: "VCC" })).toBeVisible();

  // The 3V3 pin in a second net: a reuse error, and its chip says so (3.1, 10.2).
  await addNet(page, wiring, "REUSE", "U1.1");
  await expect(checks).toContainText("U1.1 is in more than one net.");
  await expect(nets.getByRole("row", { name: /^REUSE/ })).toContainText("Error");

  // Two inputs wired only to each other: nothing drives them (5.1).
  await addNet(page, wiring, "SENSE", "U1.3, U1.4");
  await expect(checks).toContainText("Nothing drives the input-only U1.3 and U1.4.");

  // A resistor on the net drives it, and its missing pinout is a warning (5.2, 2.4).
  await nets.getByRole("button", { name: "Edit net SENSE" }).click();
  const editing = nets.getByRole("row", { name: "Editing net SENSE" });
  // Enter from the name saves; Escape here would put the net back as it was (spec 11, 10.6).
  await editing.getByRole("combobox", { name: "Pins" }).fill("U1.3, U1.4, R1.1");
  await editing.getByRole("textbox", { name: "Net name" }).press("Enter");
  await expect(nets.getByRole("row", { name: /^SENSE/ })).toContainText("R1.1");
  await expect(checks).not.toContainText("Nothing drives");
  await expect(checks).toContainText(
    `${resistor} has no pinout, so the pins of R1 aren't checked.`,
  );
  await expect(wiring).toContainText("Checks: 2 errors, 1 warning.");
  await expectNoSidewaysScroll(page);

  // Reserving lists the findings as warnings and still reserves (6.1, 10.4).
  await revisionA.getByRole("button", { name: "Reserve parts" }).click();
  const reserve = page.getByRole("dialog", { name: "Reserve parts" });
  const warnings = reserve.getByRole("region", { name: "Wiring warnings" });
  await expect(warnings).toContainText("A net joins 3.3 V and 5 V pins.");
  await expectNoSidewaysScroll(page);
  await reserve.getByRole("button", { name: "Reserve", exact: true }).click();
  await expect(reserve).toBeHidden();
  await expect(wiring.getByText(/Only a draft's wiring can change/)).toBeVisible();

  // The board's page: the nets on each pin, the free one, and the filter (7.1, 10.5, 10.6).
  await page.goto(boardPage);
  const usage = page.getByRole("region", { name: "Pin usage" });
  const first = usage.getByRole("row", { name: /^1 3V3/ });
  await expect(first).toContainText("VCC");
  await expect(first).toContainText("REUSE");
  await expect(first.getByRole("link", { name: `${station} · A` }).first()).toBeVisible();
  await expect(usage.getByRole("row", { name: /^5 GND/ })).toContainText("Free");
  await usage.getByRole("searchbox", { name: "Filter pins" }).fill("adc1");
  await expect(usage.getByRole("row", { name: /^3 GPIO34/ })).toContainText("SENSE");
  await expect(usage.getByRole("row", { name: /^1 3V3/ })).toHaveCount(0);
  await expectNoSidewaysScroll(page);
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
  // The row clears and takes focus back once the line is in, which can land a moment after the
  // table shows it: the next line waits for that, or the clearing would wipe what it types.
  const typed = newLine.getByRole("textbox", { name: "Designators" });
  await expect(typed).toBeFocused();
  await expect(typed).toHaveValue("");
}

/** A net from the add row: its name, its pins typed whole, the suggestions closed, Enter. */
async function addNet(page: Page, wiring: Locator, name: string, pins: string) {
  const newNet = wiring.getByRole("row", { name: "New net" });
  await newNet.getByRole("textbox", { name: "Net name" }).fill(name);
  await newNet.getByRole("combobox", { name: "Pins" }).fill(pins);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Enter");
  await expect(
    wiring
      .getByRole("table", { name: "Nets of the revision" })
      .getByRole("row", { name: new RegExp(`^${name}`) }),
  ).toBeVisible();
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
