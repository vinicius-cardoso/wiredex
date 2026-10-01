import { expect, type Locator, type Page, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";

/**
 * The build lifecycle end to end: a lot-counted part is stocked, a project's revision A gets a
 * BOM line that needs more than is on the shelf, and the revision walks the whole lifecycle
 * from the revision panel. Reserving is refused while the part is short, its shortage shown in
 * the dialog; a receipt covers it; reserving then succeeds and the panel shows what the build
 * holds. A recount below the reserved quantity is refused on the adjust dialog. Building drops
 * the part's total by what was reserved; dismantling into a chosen location brings the total
 * back, sitting there. The dismantled revision, no longer holding stock, is then deleted, its
 * sibling B keeping the project alive (requirements 1.1, 2.1, 2.2, 3.2, 5.1, 6.2, 6.3, 7.1,
 * 7.2, 9.2, 13.1 to 13.10).
 *
 * On a Pixel 7 the revision page with its holdings and the part's stock view never scroll the
 * page sideways: a wide table scrolls inside its own box (requirement 13.16).
 *
 * It reuses the session auth.setup.ts saved, like every other journey, and never logs out.
 * The local database keeps what a run creates, so every name carries a stamp, the worker's
 * index in it too, so repeats running side by side never share one.
 */
test("reserve, build, dismantle a revision, then delete the dismantled build", async ({ page }) => {
  // The full lifecycle across several pages: give it room beside the other journeys.
  test.slow();
  const info = test.info();
  const stamp = `${info.project.name}-${info.workerIndex}-${Date.now()}`;
  const drawer = `Drawer ${stamp}`;
  const shelf = `Shelf ${stamp}`;
  const passives = `Passives ${stamp}`;
  const resistor = `Resistor ${stamp}`;
  const project = `Controller ${stamp}`;

  // Two locations: one to receive into and reserve from, one to dismantle back into
  // (requirements 6.2, 6.3).
  await page.goto("/locations");
  await createLocation(page, drawer);
  await createLocation(page, shelf);

  // A fresh root category defaults to lot-counted, so the part below takes a loose receive
  // (requirement 1.1).
  await page.goto("/categories");
  await page.getByLabel("Add a category").fill(passives);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name: passives })).toBeVisible();

  const resistorId = await createPart(page, passives, resistor);

  // A project opens on revision A, a draft. Its BOM gets one line naming the resistor, needing
  // 4, more than the shelf holds (requirements 2.1, 2.2).
  await page.goto("/projects");
  await page.getByRole("link", { name: "New project" }).click();
  await page.getByLabel("Name", { exact: true }).fill(project);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: project })).toBeVisible();
  const revisionA = page.getByRole("region", { name: "Revision A", exact: true });
  await expect(revisionA.getByText("Draft", { exact: true })).toBeVisible();

  const bom = revisionA.getByRole("region", { name: "Bill of materials" });
  const newLine = bom.getByRole("row", { name: "New line" });
  await newLine.getByRole("textbox", { name: "Designators" }).focus();
  await page.keyboard.type("R1-4");
  await page.keyboard.press("Tab");
  await pickPart(page, newLine.getByRole("combobox", { name: "Part" }), resistor);
  await page.keyboard.press("Enter");
  const lines = bom.getByRole("table", { name: "Lines of the bill of materials" });
  await expect(lineRow(lines, resistor)).toContainText("R1–R4");

  // Reserve parts: with nothing on the shelf, the dialog refuses it as short, its report
  // naming the resistor with 4 needed, 0 available, 4 short, linking to its page (13.1, 13.3).
  await revisionA.getByRole("button", { name: "Reserve parts" }).click();
  const reserve = page.getByRole("dialog", { name: "Reserve parts" });
  await expect(reserve.getByText(`${resistor}`)).toBeVisible();
  await expect(reserve.getByText("4 needed")).toBeVisible();
  await reserve.getByRole("button", { name: "Reserve", exact: true }).click();
  const shortReport = reserve.getByRole("region", { name: "Shortages" });
  const shortRow = shortReport.getByRole("row").filter({ hasText: resistor });
  await expect(shortRow.getByRole("cell")).toHaveText(["4", "0", "4"]);
  await expect(shortRow.getByRole("link", { name: resistor })).toHaveAttribute(
    "href",
    `/parts/${resistorId}`,
  );
  await reserve.getByRole("button", { name: "Cancel" }).click();
  await expect(reserve).toBeHidden();

  // Receive 5 of the resistor into the drawer, on its own page, then back to the project.
  const projectAddress = page.url();
  await page.goto(`/parts/${resistorId}`);
  await receive(page, drawer, 5);
  const partStock = page.getByRole("region", { name: "Stock" });
  await expectTotals(partStock, { inStock: 5, reserved: 0, available: 5 });
  await page.goto(projectAddress);

  // Reserve again: now it succeeds. The status turns Reserved, and the panel shows what the
  // build reserves — 4 set aside, in the drawer (requirements 2.1, 3.2, 13.1, 13.6, 13.7).
  await revisionA.getByRole("button", { name: "Reserve parts" }).click();
  const reserveAgain = page.getByRole("dialog", { name: "Reserve parts" });
  await reserveAgain.getByRole("button", { name: "Reserve", exact: true }).click();
  await expect(reserveAgain).toBeHidden();
  await expect(revisionA.getByText("Reserved", { exact: true })).toBeVisible();
  const reservedHoldings = revisionA.getByRole("region", { name: "What this reserves" });
  await expect(reservedHoldings.getByRole("link", { name: resistor })).toBeVisible();
  await expect(reservedHoldings.getByText("4 set aside")).toBeVisible();

  // The part's stock now reads 4 reserved, and lists the build holding it (13.8). A recount of
  // the drawer below 4 is refused on the adjust dialog, saying how many are reserved (7.1).
  await page.goto(`/parts/${resistorId}`);
  await expectTotals(partStock, { inStock: 5, reserved: 4, available: 1 });
  const holdingLink = page
    .getByRole("region", { name: "Held for builds" })
    .getByRole("link", { name: new RegExp(escapeRegExp(project)) });
  await expect(holdingLink).toBeVisible();

  await partStock.getByRole("button", { name: "Adjust" }).click();
  const adjust = page.getByRole("dialog", { name: "Adjust stock" });
  await selectLocation(adjust.getByRole("combobox", { name: "Location" }), drawer);
  await adjust.getByRole("spinbutton", { name: "Counted quantity" }).fill("3");
  const belowReserved = adjust.getByRole("alert");
  await expect(belowReserved).toContainText("4 are reserved");
  await expect(adjust.getByRole("button", { name: "Adjust" })).toBeDisabled();
  await adjust.getByRole("button", { name: "Cancel" }).click();
  await expect(adjust).toBeHidden();

  // Back on the project, build the reserved revision: it confirms in place, then the status
  // turns Built (requirements 5.1, 13.1, 13.4). Its holdings now read what went into the build.
  await page.goto(projectAddress);
  await revisionA.getByRole("button", { name: "Build", exact: true }).click();
  await revisionA.getByRole("button", { name: "Build it" }).click();
  await expect(revisionA.getByText("Built", { exact: true })).toBeVisible();
  const builtHoldings = revisionA.getByRole("region", { name: "What went into this build" });
  await expect(builtHoldings.getByText("4 in the build")).toBeVisible();

  // Building consumed 4, so the part total drops from 5 to 1, none reserved (requirement 5.1).
  await page.goto(`/parts/${resistorId}`);
  await expectTotals(partStock, { inStock: 1, reserved: 0, available: 1 });
  await page.goto(projectAddress);

  // Dismantle into the shelf: the dialog picks the return location with 07's location picker,
  // and the revision turns Dismantled (requirements 6.2, 6.3, 13.5).
  await revisionA.getByRole("button", { name: "Dismantle" }).click();
  const dismantle = page.getByRole("dialog", { name: "Dismantle the build" });
  await pickLocation(page, dismantle.getByRole("combobox", { name: "Return to" }), shelf);
  await dismantle.getByRole("button", { name: "Dismantle it" }).click();
  await expect(dismantle).toBeHidden();
  await expect(revisionA.getByText("Dismantled", { exact: true })).toBeVisible();

  // The 4 are back: the total is 5 again, all of it available, and the 4 sit at the shelf
  // (requirement 6.3).
  await page.goto(`/parts/${resistorId}`);
  await expectTotals(partStock, { inStock: 5, reserved: 0, available: 5 });
  await expect(breakdownRow(page, shelf)).toContainText("4");
  await page.goto(projectAddress);

  // Fork A into B, so the project keeps a revision once A is deleted. A dismantled revision
  // holds no stock, so its Delete is offered (requirement 9.2). Forking opens B, and the
  // Revisions navigation now lists both.
  await revisionA.getByRole("button", { name: "Fork", exact: true }).click();
  const fork = page.getByRole("dialog", { name: /Fork revision A/ });
  await fork.getByRole("button", { name: "Fork", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Revision B", exact: true })).toBeVisible();

  // Open A through the Revisions navigation and delete it: it is gone, B stays as the
  // project's latest.
  const revisions = page.getByRole("navigation", { name: "Revisions" });
  await revisions.getByRole("link", { name: /^A ·/ }).click();
  await expect(revisionA.getByText("Dismantled", { exact: true })).toBeVisible();
  await revisionA.getByRole("button", { name: "Delete revision" }).click();
  await revisionA.getByRole("button", { name: "Yes, delete it" }).click();
  await expect(page.getByRole("heading", { name: "Revision B", exact: true })).toBeVisible();
});

/**
 * The revision page and the part's stock view are no wider than a phone screen, a wide table
 * scrolling in its own box (requirement 13.16). It runs in the Pixel 7 project only.
 */
test("the revision and stock views never scroll a phone sideways", async ({ page }) => {
  test.skip(test.info().project.name !== "mobile", "phone-width overflow is a Pixel 7 concern");
  const stamp = `${test.info().project.name}-${test.info().workerIndex}-${Date.now()}`;
  const drawer = `Drawer ${stamp}`;
  const passives = `Passives ${stamp}`;
  const resistor = `Resistor ${stamp}`;
  const project = `Controller ${stamp}`;

  await page.goto("/locations");
  await createLocation(page, drawer);

  await page.goto("/categories");
  await page.getByLabel("Add a category").fill(passives);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name: passives })).toBeVisible();

  const resistorId = await createPart(page, passives, resistor);
  await receive(page, drawer, 5);

  // A project with a BOM line, reserved, so the revision page carries its holdings.
  await page.goto("/projects");
  await page.getByRole("link", { name: "New project" }).click();
  await page.getByLabel("Name", { exact: true }).fill(project);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: project })).toBeVisible();
  const revisionA = page.getByRole("region", { name: "Revision A", exact: true });
  const bom = revisionA.getByRole("region", { name: "Bill of materials" });
  const newLine = bom.getByRole("row", { name: "New line" });
  await newLine.getByRole("textbox", { name: "Designators" }).focus();
  await page.keyboard.type("R1-4");
  await page.keyboard.press("Tab");
  await pickPart(page, newLine.getByRole("combobox", { name: "Part" }), resistor);
  await page.keyboard.press("Enter");
  await expect(
    bom
      .getByRole("table", { name: "Lines of the bill of materials" })
      .getByRole("link", { name: resistor }),
  ).toBeVisible();

  await revisionA.getByRole("button", { name: "Reserve parts" }).click();
  const reserve = page.getByRole("dialog", { name: "Reserve parts" });
  await reserve.getByRole("button", { name: "Reserve", exact: true }).click();
  await expect(reserve).toBeHidden();

  // The revision page, holdings and all, fits the phone.
  await expect(revisionA.getByText("Reserved", { exact: true })).toBeVisible();
  await expectNoSidewaysScroll(page);

  // The part's stock view, with its three-column breakdown, fits the phone too.
  await page.goto(`/parts/${resistorId}`);
  const partStock = page.getByRole("region", { name: "Stock" });
  await expectTotals(partStock, { inStock: 5, reserved: 4, available: 1 });
  await expectNoSidewaysScroll(page);
});

/** Adds a top-level location and waits for it to appear in the tree. */
async function createLocation(page: Page, name: string) {
  await page.getByLabel("Add a location").fill(name);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name })).toBeVisible();
}

/** Defines a lot-counted part in CATEGORY and answers its id, read off the part page's address. */
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
  await selectLocation(dialog.getByRole("combobox", { name: "Location" }), location);
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

/**
 * Picks a location in a stock dialog's native `<select>` by the name it was given. The option
 * text is `name (WX-L-NNNN)`, and the short code is minted by the server, so match on the name
 * and select the option by its own value rather than guess the code.
 */
async function selectLocation(combobox: Locator, name: string) {
  const value = await combobox
    .getByRole("option", { name: new RegExp(escapeRegExp(name)) })
    .getAttribute("value");
  if (value === null) throw new Error(`no option for the location ${name}`);
  await combobox.selectOption(value);
}

/**
 * Picks a location in 07's typeahead location picker as a person would: types part of its
 * name, waits for the match to be offered, moves to it and takes it with Enter. The box then
 * shows the picked location's path and shuts its list.
 */
async function pickLocation(page: Page, combobox: Locator, name: string) {
  await combobox.focus();
  await combobox.fill(name);
  await expect(page.getByRole("option", { name: new RegExp(escapeRegExp(name)) })).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(combobox).toHaveAttribute("aria-expanded", "false");
  await expect(combobox).toHaveValue(new RegExp(escapeRegExp(name)));
}

/**
 * The stock region's total line reads on hand, reserved and available for the whole part. It
 * is one paragraph, found by its "in stock" text, so its counts don't clash with the same
 * words in the per-location breakdown or the holdings list beneath it.
 */
async function expectTotals(
  stock: Locator,
  totals: { inStock: number; reserved: number; available: number },
) {
  const line = stock.locator("p").filter({ hasText: "in stock" }).first();
  await expect(line).toContainText(`${totals.inStock} in stock`);
  await expect(line).toContainText(`${totals.reserved} reserved`);
  await expect(line).toContainText(`${totals.available} available`);
}

/** A line of the BOM's table, found by its part's name. */
function lineRow(lines: Locator, part: string): Locator {
  return lines.getByRole("row").filter({ has: lines.page().getByRole("link", { name: part }) });
}

/** The stock-by-location row for a location, found by the name it was given. */
function breakdownRow(page: Page, name: string): Locator {
  return page.getByRole("table", { name: "Stock by location" }).getByRole("row", { name });
}

/** Escapes the stamp so its characters aren't read as a pattern. */
function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
