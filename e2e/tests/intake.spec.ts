import { expect, type Locator, type Page, test } from "@playwright/test";

/**
 * The intake end to end: parts come in by quick-add from the keyboard, by duplicating a part,
 * and from a sheet with Portuguese headers, previewed, fixed in place and imported whole. The
 * stock and the units they bring are then found where the rest of the app shows them. It
 * exercises the whole slice end to end (all requirements).
 *
 * It reuses the session auth.setup.ts saved, like every other journey, and never logs out.
 * The local database keeps what a run creates, so every name, part number and the MAC carry a
 * stamp. The worker's index is in it too, so repeats running side by side never share one.
 */
test("quick-add, duplicate and import parts, then find their stock and units", async ({ page }) => {
  // Three quick adds, a duplicate, an import and a search: as long as the other long journeys,
  // and it reached the default 30 seconds beside them, so it gets the room they get.
  test.slow();
  const info = test.info();
  const now = Date.now();
  const stamp = `${info.project.name}-${info.workerIndex}-${now}`;
  const bin = `Bin ${stamp}`;
  const passives = `Passives ${stamp}`;
  const boards = `Boards ${stamp}`;
  const nowhere = `Nowhere ${stamp}`;
  const partA = `Resistor 10k ${stamp}`;
  const partB = `Resistor 4k7 ${stamp}`;
  const partC = `Resistor 1k ${stamp}`;
  const partD = `Capacitor 100n ${stamp}`;
  const boardE = `ESP32 board ${stamp}`;
  const partF = `Capacitor 10u ${stamp}`;
  const mpnA = `RA-${stamp}`;
  const mpnB = `RB-${stamp}`;
  const mpnC = `RC-${stamp}`;
  // A locally administered MAC: the worker in one octet and the time in the last four, so no
  // other run's board holds it. It goes into the sheet in an upper-case hyphen spelling and is
  // stored canonical (lower-case, colon-separated), which is what the search is given.
  const worker = (info.workerIndex % 256).toString(16).padStart(2, "0");
  const time = (now % 2 ** 32).toString(16).padStart(8, "0");
  const canonical = `02:${worker}:${time.match(/../g)?.join(":")}`;
  const typedMac = canonical.replace(/:/g, "-").toUpperCase();

  // Set up through the pages: a bin to stock into, a lot-counted category and one tracked
  // individually, whose parts come in as units (requirements 1.2, 1.3).
  await page.goto("/locations");
  await page.getByLabel("Add a location").fill(bin);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name: bin })).toBeVisible();

  await page.goto("/categories");
  await createCategory(page, passives);
  await createCategory(page, boards);
  await page.getByRole("treeitem", { name: boards }).click();
  const tracking = page
    .getByRole("region", { name: `The category ${boards}` })
    .getByLabel("Tracked individually");
  await tracking.selectOption("yes");
  // The select follows the stored flag, so this waits until the change is saved.
  await expect(tracking).toHaveValue("yes");

  // Alt+N on the dashboard opens quick-add, focus in its first field (requirements 2.2, 2.3).
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  // The dashboard's count of parts, to see it move without the page being opened again.
  const partsTile = page.locator('nav[aria-label="The bench at a glance"] a[href="/parts"]');
  const partsCounted = async () =>
    Number.parseInt((await partsTile.innerText()).replace(/\D/g, ""), 10);
  await expect.poll(partsCounted).toBeGreaterThanOrEqual(0);
  const partsBefore = await partsCounted();
  await page.keyboard.press("Alt+KeyN");
  const quickAdd = page.getByRole("dialog", { name: "Quick add" });
  await expect(quickAdd).toBeVisible();
  const category = quickAdd.getByLabel("Category");
  await expect(category).toBeFocused();

  // Part A: 25 into the bin, picked by typing its name; Enter submits (requirements 1.2, 2.3,
  // 9.2).
  await category.selectOption({ label: passives });
  await quickAdd.getByLabel("Name", { exact: true }).fill(partA);
  await quickAdd.getByLabel("Part number").fill(mpnA);
  const location = quickAdd.getByRole("combobox", { name: "Location" });
  await pickLocation(location, bin);
  const quantity = quickAdd.getByLabel("Quantity");
  await quantity.fill("25");
  await quantity.press("Enter");
  await expect(quickAdd.getByText(`Added ${partA}. In stock at ${bin}: 25.`)).toBeVisible();
  // Behind the dialog the dashboard counts the new part at once. Other journeys add parts too,
  // but nothing they write reaches this page, so only this write can have moved the count.
  await expect.poll(partsCounted).toBeGreaterThan(partsBefore);

  // *Add another* is focused and keeps the category and the bin; the name is next
  // (requirements 2.5, 2.6).
  const another = quickAdd.getByRole("button", { name: "Add another" });
  await expect(another).toBeFocused();
  await another.press("Enter");
  await expect(category.locator("option:checked")).toHaveText(passives);
  await expect(location).toHaveValue(bin);
  const name = quickAdd.getByLabel("Name", { exact: true });
  await expect(name).toBeFocused();
  await name.fill(partB);
  await quickAdd.getByLabel("Part number").fill(mpnB);
  await quantity.fill("10");
  await quantity.press("Enter");
  await expect(quickAdd.getByText(`Added ${partB}. In stock at ${bin}: 10.`)).toBeVisible();

  // *Open the part* lands on B's page, its stock already there (requirement 2.5).
  await quickAdd.getByRole("link", { name: "Open the part" }).click();
  await expect(page.getByRole("heading", { name: partB })).toBeVisible();
  await expect(page.getByRole("region", { name: "Stock" }).getByText("10 in stock")).toBeVisible();

  // Duplicate B: the name starts selected, so typing replaces it, and the part number blank
  // (requirement 3.1). Saved alone, C is B's category with no stock (3.2, 3.3).
  await page.getByRole("button", { name: "Duplicate" }).click();
  const duplicate = page.getByRole("dialog", { name: `Duplicate ${partB}` });
  const copyName = duplicate.getByLabel("Name", { exact: true });
  await expect(copyName).toBeFocused();
  await expect(copyName).toHaveValue(partB);
  await expect.poll(() => selection(copyName)).toEqual([0, partB.length]);
  const copyMpn = duplicate.getByLabel("Part number");
  await expect(copyMpn).toHaveValue("");
  await page.keyboard.type(partC);
  await expect(copyName).toHaveValue(partC);
  await copyMpn.fill(mpnC);
  await copyMpn.press("Enter");
  await expect(duplicate.getByText(`Added ${partC}.`, { exact: true })).toBeVisible();
  await duplicate.getByRole("link", { name: "Open the part" }).click();
  await expect(page.getByRole("heading", { name: partC })).toBeVisible();
  await expect(page.getByRole("definition").filter({ hasText: passives })).toBeVisible();
  await expect(page.getByRole("region", { name: "Stock" }).getByText("0 in stock")).toBeVisible();

  // Import a sheet saved with Portuguese headers and semicolons: a new part into the bin by
  // its path, more of A by its part number, a board with a MAC, and a row whose location
  // doesn't exist (requirements 4.2, 4.3, 5.1, 6.1, 6.2, 6.4).
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Parts" })
    .click();
  await page.getByRole("link", { name: "Import from a sheet" }).click();
  await expect(page.getByRole("heading", { name: "Import from a sheet", level: 1 })).toBeVisible();
  const rows = (last: string) =>
    [
      "categoria;nome;código do fabricante;local;quantidade;endereço mac",
      `${passives};${partD};;${bin};100;`,
      `;;${mpnA};${bin};5;`,
      `${boards};${boardE};;${bin};1;${typedMac}`,
      `${passives};${partF};;${last};3;`,
    ].join("\r\n");
  const broken = rows(nowhere);
  await page.getByLabel("Choose a CSV file").setInputFiles({
    name: "estoque.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(`${broken}\r\n`, "utf8"),
  });
  const sheet = page.getByRole("textbox", { name: "Sheet text" });
  await expect(sheet).toHaveValue(new RegExp(escapeRegExp(nowhere)));

  // The preview names the bad row's problem and keeps *Import* off (requirements 7.2, 11.2,
  // 11.3).
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  const table = page.getByRole("table", { name: "What each row of the sheet will do" });
  const badRow = table.getByRole("row").filter({ hasText: partF });
  await expect(badRow).toContainText("That location isn't in the tree.");
  const importButton = page.getByRole("button", { name: "Import", exact: true });
  await expect(importButton).toHaveAttribute("aria-disabled", "true");

  // Fixed in the text box and previewed again, the sheet is clean and imports whole
  // (requirements 8.1, 11.4, 11.5).
  await sheet.fill(rows(bin));
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  // The summary says "problems" until the new preview is in, so this waits for it.
  await expect(page.getByRole("status", { name: "Import summary" })).toContainText(
    "The preview is clean.",
  );
  await expect(badRow).not.toContainText("That location isn't in the tree.");
  await expect(importButton).not.toHaveAttribute("aria-disabled");
  await importButton.click();
  await expect(page.getByRole("heading", { name: "Imported" })).toBeVisible();
  const codes = page.getByRole("list", { name: "Unit codes" });
  const unitLink = codes.getByRole("link", { name: /^WX-U-\d{4,}$/ });
  await expect(unitLink).toHaveCount(1);
  await expect(codes).toContainText(canonical);
  const code = (await unitLink.textContent())?.trim() ?? "";

  // A has its quick-added 25 and the sheet's 5 (requirement 8.1).
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Parts" })
    .click();
  // Every journey adds parts beside this one, so the list is narrowed to A before it is opened.
  // On a phone the filters fold behind a toggle.
  const filtersToggle = page.getByRole("button", { name: "Show filters" });
  if (await filtersToggle.isVisible()) await filtersToggle.click();
  await page.getByLabel("Search by name or number").fill(partA);
  await page.getByRole("link", { name: partA, exact: true }).click();
  await expect(page.getByRole("heading", { name: partA })).toBeVisible();
  await expect(page.getByRole("region", { name: "Stock" }).getByText("30 in stock")).toBeVisible();

  // Narrowed to this run's parts out of stock, the list holds C, duplicated with none, and
  // not A; every other part of the run came in with stock.
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Parts" })
    .click();
  const showFilters = page.getByRole("button", { name: "Show filters" });
  if (await showFilters.isVisible()) await showFilters.click();
  await page.getByLabel("Search by name or number").fill(stamp);
  await page.getByLabel("Stock").selectOption({ label: "Out of stock" });
  await expect(page.getByRole("rowheader", { name: partC, exact: true })).toBeVisible();
  await expect(page.getByRole("rowheader")).toHaveCount(1);

  // The board is a unit like any other: the Boards list finds it by its MAC (requirement 6.4).
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Boards" })
    .click();
  await expect(page.getByRole("heading", { name: "Boards", level: 1 })).toBeVisible();
  await page.getByLabel("Search by code, serial or MAC").fill(canonical);
  const hit = page.getByRole("row").filter({ hasText: code });
  await expect(hit).toContainText(canonical);
  await expect(hit.getByRole("link", { name: code })).toBeVisible();
});

/** Adds a top-level category and waits for it to appear in the tree. */
async function createCategory(page: Page, name: string) {
  await page.getByLabel("Add a category").fill(name);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name })).toBeVisible();
}

/**
 * Picks a location in the picker as a person would: types its name, moves to the one match
 * and takes it with Enter. The box then shows the picked location's path.
 */
async function pickLocation(combobox: Locator, name: string) {
  await combobox.fill(name);
  await expect(combobox).toHaveAttribute("aria-expanded", "true");
  await combobox.press("ArrowDown");
  await combobox.press("Enter");
  await expect(combobox).toHaveAttribute("aria-expanded", "false");
  await expect(combobox).toHaveValue(name);
}

/** Where a text field's selection starts and ends. */
function selection(field: Locator): Promise<[number | null, number | null]> {
  return field.evaluate((input: HTMLInputElement) => [input.selectionStart, input.selectionEnd]);
}

/** Escapes the stamp so its characters aren't read as a pattern. */
function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
