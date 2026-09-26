import { expect, test } from "@playwright/test";

/**
 * The catalog end to end: a category, a field on that category, and a part whose value is
 * typed the way it is printed on the part.
 *
 * It reuses the session auth.setup.ts saved, like every other journey. The local database
 * keeps what a run creates, so the names carry a stamp.
 */
test("a category, a resistance field, and a part typed as 4k7", async ({ page }) => {
  const stamp = `${test.info().project.name}-${Date.now()}`;
  const category = `Resistors ${stamp}`;
  const part = `Resistor 4k7 ${stamp}`;

  await page.goto("/categories");
  await page.getByLabel("Add a category").fill(category);
  await page.getByRole("button", { name: "Add", exact: true }).click();

  const branch = page.getByRole("treeitem", { name: category });
  await expect(branch).toBeVisible();
  await branch.click();

  // Resistance, in ohms, needed on every part filed here (requirements 2.1, 2.2, 7.7).
  const fields = page.getByRole("region", { name: `Fields of ${category}` });
  await fields.getByRole("button", { name: "Add a field" }).click();
  await fields.getByLabel("Key").fill("resistance");
  await fields.getByLabel("Label").fill("Resistance");
  await fields.getByLabel("Kind").selectOption("number");
  await fields.getByLabel("Unit").fill("Ω");
  await fields.getByLabel("Required").check();
  await fields.getByRole("button", { name: "Save" }).click();

  const field = fields.getByRole("listitem").filter({ hasText: "resistance" });
  await expect(field).toContainText("Resistance");
  await expect(field).toContainText("Ω");
  await expect(field).toContainText("Required");

  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Parts" })
    .click();
  await page.getByRole("link", { name: "New part" }).click();
  await expect(page.getByRole("heading", { name: "New part" })).toBeVisible();

  await page.getByLabel("Category").selectOption({ label: category });
  await page.getByLabel("Name", { exact: true }).fill(part);
  const resistance = page.getByLabel("Resistance");
  await resistance.fill("4k7");

  // The normalized value shows beside the field as it is typed, and what was typed stays
  // exactly as typed (requirement 7.3).
  await expect(page.getByText("= 4.7kΩ")).toBeVisible();
  await expect(resistance).toHaveValue("4k7");

  await page.getByRole("button", { name: "Save" }).click();

  // Saving lands on the part, which is where stored values are shown: 4k7 typed, 4.7k read
  // back (requirement 3.9). The list deliberately carries no attribute values (8.2).
  await expect(page.getByRole("heading", { name: part })).toBeVisible();
  await expect(page.getByText("4.7kΩ")).toBeVisible();

  await page.getByRole("link", { name: "← Parts" }).click();
  // The parts page is a search; on a phone its filters fold behind a toggle (requirement 6.7).
  const showFilters = page.getByRole("button", { name: "Show filters" });
  if (await showFilters.isVisible()) await showFilters.click();
  await page.getByLabel("Search by name or number").fill(part);

  const row = page.getByRole("row").filter({ hasText: part });
  await expect(row).toContainText(category);
  await expect(row.getByRole("link", { name: part })).toBeVisible();
});
