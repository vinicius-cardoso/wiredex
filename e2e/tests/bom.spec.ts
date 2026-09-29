import { expect, type Locator, type Page, test } from "@playwright/test";

/**
 * The bill of materials end to end: a consumables category is marked not stocked, three parts
 * are defined and one of them stocked, and revision A's BOM is typed from the keyboard alone.
 * Its shortage report follows each line, a taken designator is refused on its field, a line
 * is edited and an edit abandoned, a receipt covers the last shortage, a fork carries the BOM,
 * the catalog keeps a part two BOMs name, and a line removed from the fork stays on its source.
 * On a phone the BOM, its editor and its report never scroll the page sideways (all
 * requirements, 11.17 in the Pixel 7 project).
 *
 * It reuses the session auth.setup.ts saved, like every other journey, and never logs out.
 * The local database keeps what a run creates, so every name carries a stamp, the worker's
 * index in it too, so repeats running side by side never share one.
 */
test("type a BOM by keyboard, follow its shortages, fork it, and keep the parts it names", async ({
  page,
}) => {
  // The longest journey: it builds a BOM, forks it and deletes parts, beside the others.
  test.slow();
  const info = test.info();
  const stamp = `${info.project.name}-${info.workerIndex}-${Date.now()}`;
  const drawer = `Drawer ${stamp}`;
  const consumables = `Consumables ${stamp}`;
  const passives = `Passives ${stamp}`;
  const resistor = `Resistor ${stamp}`;
  const sensor = `Sensor ${stamp}`;
  const wire = `Wire ${stamp}`;
  const station = `Station ${stamp}`;

  // Set up through the pages: a drawer, a not-stocked root category and a stocked one, three
  // parts, and 3 of the resistor received (requirements 1.1, 11.10).
  await page.goto("/locations");
  await page.getByLabel("Add a location").fill(drawer);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name: drawer })).toBeVisible();

  // Both at the root: once a category is selected, the add field adds under it.
  await page.goto("/categories");
  await createCategory(page, consumables);
  await createCategory(page, passives);
  await page.getByRole("treeitem", { name: consumables }).click();
  const stocking = page
    .getByRole("region", { name: `The category ${consumables}` })
    .getByLabel("Not stocked");
  await stocking.selectOption("yes");
  // The select follows the stored flag, so this waits until the change is saved.
  await expect(stocking).toHaveValue("yes");

  const resistorId = await createPart(page, passives, resistor);
  await receive(page, drawer, 3);
  const sensorId = await createPart(page, passives, sensor);
  const wireId = await createPart(page, consumables, wire);

  // The wire's page says it isn't stocked and offers no receipt (requirement 11.11).
  const wireStock = page.getByRole("region", { name: "Stock" });
  await expect(
    wireStock.getByText(/Not stocked: this part's category is for consumables/),
  ).toBeVisible();
  await expect(wireStock.getByRole("button", { name: "Receive" })).toHaveCount(0);

  // A project, which opens on revision A, a draft whose BOM is empty.
  await page.goto("/projects");
  await page.getByRole("link", { name: "New project" }).click();
  await page.getByLabel("Name", { exact: true }).fill(station);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: station })).toBeVisible();
  const revisionA = page.getByRole("region", { name: "Revision A", exact: true });
  const bom = revisionA.getByRole("region", { name: "Bill of materials" });
  const newLine = bom.getByRole("row", { name: "New line" });
  const designators = newLine.getByRole("textbox", { name: "Designators" });
  const part = newLine.getByRole("combobox", { name: "Part" });
  const quantity = newLine.getByRole("spinbutton", { name: "Quantity" });

  // By keyboard alone: `r1-4` previews as R1–R4 and 4, the quantity 4 and read-only; Tab, the
  // resistor picked with the arrow and Enter, and Enter adds the line and puts focus back on
  // Designators (requirements 11.2, 11.3, 11.4, 11.16).
  await designators.focus();
  await page.keyboard.type("r1-4");
  await expect(designators).toHaveAccessibleDescription("Reads as R1–R4; quantity 4.");
  await expect(quantity).toHaveValue("4");
  await expect(quantity).not.toBeEditable();
  await page.keyboard.press("Tab");
  await expect(part).toBeFocused();
  await pickPart(page, part, resistor);
  await page.keyboard.press("Enter");
  const lines = bom.getByRole("table", { name: "Lines of the bill of materials" });
  await expect(lineRow(lines, resistor)).toContainText("R1–R4");
  await expect(designators).toBeFocused();
  await expect(designators).toHaveValue("");

  await page.keyboard.type("U1");
  await page.keyboard.press("Tab");
  await pickPart(page, part, sensor);
  await page.keyboard.press("Enter");
  await expect(lineRow(lines, sensor)).toContainText("U1");
  await expect(designators).toBeFocused();

  // The wire has no designators: quantity 1, and the amount in the notes (decision 7).
  await page.keyboard.press("Tab");
  await pickPart(page, part, wire);
  await page.keyboard.press("Tab");
  await expect(quantity).toBeFocused();
  await page.keyboard.type("1");
  await page.keyboard.press("Tab");
  await page.keyboard.type("2 m");
  await page.keyboard.press("Enter");
  await expect(lineRow(lines, wire)).toContainText("2 m");
  await expect(lineRow(lines, wire)).toContainText("Not stocked");

  // The report: the resistor short 1 (4 needed, 3 there), the sensor short 1, the wire not
  // stocked, and each short part linking to its page (requirements 6.1 to 6.6, 11.8).
  const report = bom.getByRole("region", { name: "Shortages" });
  const missing = report.getByRole("table", { name: "Parts short or unknown" });
  await expect(missing.getByRole("row", { name: resistor }).getByRole("cell")).toHaveText([
    "4",
    "3",
    "1",
  ]);
  await expect(missing.getByRole("row", { name: sensor }).getByRole("cell")).toHaveText([
    "1",
    "0",
    "1",
  ]);
  await expect(report.getByRole("definition").nth(4)).toHaveText("1");
  await expect(missing.getByRole("link", { name: resistor })).toHaveAttribute(
    "href",
    `/parts/${resistorId}`,
  );
  await expect(missing.getByRole("link", { name: sensor })).toHaveAttribute(
    "href",
    `/parts/${sensorId}`,
  );
  await expect(missing.getByRole("link", { name: wire })).toHaveCount(0);
  await expectNoSidewaysScroll(page);

  // `R4` for the sensor: refused on Designators, naming the line that holds it (4.6, 11.7).
  await page.keyboard.type("R4");
  await page.keyboard.press("Tab");
  await pickPart(page, part, sensor);
  await page.keyboard.press("Enter");
  await expect(designators).toHaveAttribute("aria-invalid", "true");
  await expect(designators).toBeFocused();
  await expect(designators).toHaveAccessibleDescription(/R4 is already on the line R1–R4\./);
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.press("Backspace");

  // The resistor's line edited in its row to R1-3 and saved with Enter: 3 needed, 3 there, so
  // it isn't short any more (requirement 11.5).
  await lines.getByRole("button", { name: "Edit line R1–R4" }).focus();
  await page.keyboard.press("Enter");
  const editing = lines.getByRole("row", { name: "Editing line R1–R4" });
  const editedDesignators = editing.getByRole("textbox", { name: "Designators" });
  await expect(editedDesignators).toBeFocused();
  await expectNoSidewaysScroll(page);
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.type("R1-3");
  await page.keyboard.press("Enter");
  const editR1R3 = lines.getByRole("button", { name: "Edit line R1–R3" });
  await expect(editR1R3).toBeFocused();
  await expect(lineRow(lines, resistor).getByRole("cell").nth(2)).toHaveText("3");
  await expect(missing.getByRole("row", { name: resistor })).toHaveCount(0);

  // Edited again, the notes changed, and Escape: nothing changed, focus back on Edit.
  await page.keyboard.press("Enter");
  await lines
    .getByRole("row", { name: "Editing line R1–R3" })
    .getByRole("textbox", { name: "Notes" })
    .focus();
  await page.keyboard.type("pull-ups");
  await page.keyboard.press("Escape");
  await expect(editR1R3).toBeFocused();
  await expect(lineRow(lines, resistor).getByRole("cell").nth(3)).toHaveText("—");

  // 1 of the sensor received on its page; A's BOM then has nothing short (requirement 6.7).
  const projectAddress = page.url();
  await page.goto(`/parts/${sensorId}`);
  await receive(page, drawer, 1);
  await page.goto(projectAddress);
  await expect(bom.getByText("Nothing is short.")).toBeVisible();

  // Fork A into B: B's BOM holds the same three lines (requirement 7.1).
  await revisionA.getByRole("button", { name: "Fork", exact: true }).focus();
  await page.keyboard.press("Enter");
  const fork = page.getByRole("dialog", { name: "Fork revision A" });
  await expect(fork.getByLabel("Label")).toHaveValue("B");
  await fork.getByRole("button", { name: "Fork", exact: true }).click();
  const revisionB = page.getByRole("region", { name: "Revision B", exact: true });
  const linesB = revisionB
    .getByRole("region", { name: "Bill of materials" })
    .getByRole("table", { name: "Lines of the bill of materials" });
  await expect(lineRow(linesB, resistor)).toContainText("R1–R3");
  await expect(lineRow(linesB, sensor)).toContainText("U1");
  await expect(lineRow(linesB, wire)).toContainText("2 m");
  const addressB = page.url();
  // The project's own address now opens B, its latest; A keeps an address of its own.
  const addressA = await revisionB
    .getByRole("link", { name: "A", exact: true })
    .getAttribute("href");
  if (!addressA) throw new Error("no link from B to the revision it was forked from");

  // The sensor can't be deleted: both BOMs name it, each a link (requirements 8.1, 11.13).
  await page.goto(`/parts/${sensorId}`);
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("button", { name: "Delete part" }).click();
  const kept = page.getByRole("alert");
  await expect(kept.getByRole("link", { name: `${station}, revision A` })).toBeVisible();
  await expect(kept.getByRole("link", { name: `${station}, revision B` })).toBeVisible();

  // On B, the sensor's line removed after asking in its row: gone from B, still on A (11.6).
  await page.goto(addressB);
  await linesB.getByRole("button", { name: "Remove line U1" }).focus();
  await page.keyboard.press("Enter");
  const question = linesB.getByRole("group", { name: "Remove line U1?" });
  await expect(question.getByRole("button", { name: "Keep" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Enter");
  await expect(lineRow(linesB, sensor)).toHaveCount(0);
  await expect(lineRow(linesB, resistor)).toBeVisible();

  await page.goto(addressA);
  await expect(lineRow(lines, sensor)).toContainText("U1");
  await expect(page.getByRole("link", { name: wire }).first()).toHaveAttribute(
    "href",
    `/parts/${wireId}`,
  );
  await expectNoSidewaysScroll(page);
});

async function createCategory(page: Page, name: string) {
  await page.getByLabel("Add a category").fill(name);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name })).toBeVisible();
}

/** Defines a part in CATEGORY and answers its id, read off the part page's address. */
async function createPart(page: Page, category: string, name: string): Promise<string> {
  await page.goto("/parts");
  await page.getByRole("link", { name: "New part" }).click();
  await page.getByLabel("Category").selectOption({ label: category });
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  const id = new URL(page.url()).pathname.split("/").at(-1);
  if (!id) throw new Error(`no id in the address of ${name}`);
  return id;
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

/**
 * Picks a part in the focused picker as a person would: types its name, waits for it to be
 * offered, moves to it and takes it with Enter. The box then shows the picked part's name.
 */
async function pickPart(page: Page, picker: Locator, name: string) {
  await page.keyboard.type(name);
  await expect(page.getByRole("option", { name })).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(picker).toHaveAttribute("aria-expanded", "false");
  await expect(picker).toHaveValue(name);
}

/** A line of the BOM's table, found by its part's name. */
function lineRow(lines: Locator, part: string): Locator {
  return lines.getByRole("row").filter({ has: lines.page().getByRole("link", { name: part }) });
}

/** The page is no wider than the screen: a wide table scrolls in its own box (11.17). */
async function expectNoSidewaysScroll(page: Page) {
  const [scrollWidth, innerWidth] = await page.evaluate(() => [
    document.documentElement.scrollWidth,
    window.innerWidth,
  ]);
  expect(scrollWidth).toBeLessThanOrEqual(innerWidth);
}

/** Escapes the stamp so its characters aren't read as a pattern. */
function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
