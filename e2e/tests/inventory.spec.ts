import { expect, test } from "@playwright/test";

/**
 * The inventory end to end: a part is stocked, split across two locations, then recounted,
 * and the part page tells the truth at every step.
 *
 * It reuses the session auth.setup.ts saved, like every other journey, and never logs out.
 * The local database keeps what a run creates, so every name carries a stamp. The category
 * leaves "tracked individually" unset, so it resolves to lot-counted and a loose receive is
 * allowed (requirement 6.2).
 */
test("receive, move and recount a part across two locations", async ({ page }) => {
  const stamp = `${test.info().project.name}-${Date.now()}`;
  const category = `Passives ${stamp}`;
  const part = `Resistor 10k ${stamp}`;
  const drawer = `Drawer ${stamp}`;
  const box = `Parts box ${stamp}`;

  // Two locations to split the stock between (requirements 1.1, 1.2).
  await page.goto("/locations");
  await createLocation(page, drawer);
  await createLocation(page, box);

  // A lot-counted part to stock: a fresh root category inherits nothing, so it defaults to
  // lot-counted and the receive below is accepted (requirements 6.2, 4.1).
  await page.goto("/categories");
  await page.getByLabel("Add a category").fill(category);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name: category })).toBeVisible();

  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Parts" })
    .click();
  await page.getByRole("link", { name: "New part" }).click();
  await page.getByLabel("Category").selectOption({ label: category });
  await page.getByLabel("Name", { exact: true }).fill(part);
  await page.getByRole("button", { name: "Save" }).click();

  // Saving lands on the part page, where its stock lives (requirement 7.3).
  await expect(page.getByRole("heading", { name: part })).toBeVisible();
  const stock = page.getByRole("region", { name: "Stock" });
  await expect(stock.getByText("0 in stock")).toBeVisible();

  // Receive 100 into the drawer; the total shows 100 in place, no reload (requirements 4.1, 9.4).
  await stock.getByRole("button", { name: "Receive" }).click();
  const receive = page.getByRole("dialog", { name: "Receive stock" });
  await selectLocation(receive.getByRole("combobox", { name: "Location" }), drawer);
  await receive.getByRole("spinbutton", { name: "Quantity" }).fill("100");
  await receive.getByRole("button", { name: "Receive" }).click();
  await expect(stock.getByText("100 in stock")).toBeVisible();
  await expect(breakdownRow(page, drawer)).toContainText("100");

  // Move 40 to the parts box; the total is unchanged but the split is 60 / 40
  // (requirements 4.5, 4.6, 9.3).
  await stock.getByRole("button", { name: "Move" }).click();
  const move = page.getByRole("dialog", { name: "Move stock" });
  await selectLocation(move.getByRole("combobox", { name: "From" }), drawer);
  await selectLocation(move.getByRole("combobox", { name: "To" }), box);
  await move.getByRole("spinbutton", { name: "Quantity" }).fill("40");
  await move.getByRole("button", { name: "Move" }).click();
  await expect(stock.getByText("100 in stock")).toBeVisible();
  await expect(breakdownRow(page, drawer)).toContainText("60");
  await expect(breakdownRow(page, box)).toContainText("40");

  // Recount the drawer lot to 55; the total follows the recount to 95 (requirements 4.3, 9.5).
  await stock.getByRole("button", { name: "Adjust" }).click();
  const adjust = page.getByRole("dialog", { name: "Adjust stock" });
  await selectLocation(adjust.getByRole("combobox", { name: "Location" }), drawer);
  await adjust.getByRole("spinbutton", { name: "Counted quantity" }).fill("55");
  await adjust.getByRole("combobox", { name: "Reason" }).selectOption({ label: "Recount" });
  await adjust.getByRole("button", { name: "Adjust" }).click();
  await expect(stock.getByText("95 in stock")).toBeVisible();
  await expect(breakdownRow(page, drawer)).toContainText("55");
  await expect(breakdownRow(page, box)).toContainText("40");
});

/** Adds a top-level location and waits for it to appear in the tree. */
async function createLocation(page: import("@playwright/test").Page, name: string) {
  await page.getByLabel("Add a location").fill(name);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name })).toBeVisible();
}

/**
 * Picks a location in a stock dialog by the name it was given. The option text is
 * `name (WX-L-NNNN)`, and the short code is minted by the server, so match on the name and
 * select the option by its own value rather than guess the code.
 */
async function selectLocation(combobox: import("@playwright/test").Locator, name: string) {
  const value = await combobox
    .getByRole("option", { name: new RegExp(escapeRegExp(name)) })
    .getAttribute("value");
  if (value === null) throw new Error(`no option for the location ${name}`);
  await combobox.selectOption(value);
}

/** Escapes the stamp so its characters aren't read as a pattern. */
function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** The stock-by-location row for a location, found by the name it was given. */
function breakdownRow(page: import("@playwright/test").Page, name: string) {
  return page.getByRole("table", { name: "Stock by location" }).getByRole("row", { name });
}
