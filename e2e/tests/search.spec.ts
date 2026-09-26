import { expect, test } from "@playwright/test";

/**
 * Parametric search end to end: a category with a resistance attribute and three resistors
 * typed as they are printed (220R, 4k7, 10k). Filtering 1k–10k keeps 4k7 and 10k but not
 * 220R; sorting by resistance orders them; and the search survives a reload because it lives
 * in the address (requirements 1, 2, 4, 6 — end to end).
 *
 * It reuses the session auth.setup.ts saved, like every other journey. The local database
 * keeps what a run creates, so the names carry a stamp.
 */
test("filter resistors by resistance, sort, and keep the search across a reload", async ({
  page,
}) => {
  const stamp = `${test.info().project.name}-${Date.now()}`;
  const category = `Resistors ${stamp}`;
  const r220 = { name: `R 220R ${stamp}`, value: "220R" };
  const r4k7 = { name: `R 4k7 ${stamp}`, value: "4k7" };
  const r10k = { name: `R 10k ${stamp}`, value: "10k" };
  const resistors = [r220, r4k7, r10k];

  // A category with a required resistance attribute, in ohms (requirement 2.1).
  await page.goto("/categories");
  await page.getByLabel("Add a category").fill(category);
  await page.getByRole("button", { name: "Add", exact: true }).click();

  const branch = page.getByRole("treeitem", { name: category });
  await expect(branch).toBeVisible();
  await branch.click();

  const fields = page.getByRole("region", { name: `Fields of ${category}` });
  await fields.getByRole("button", { name: "Add a field" }).click();
  await fields.getByLabel("Key").fill("resistance");
  await fields.getByLabel("Label").fill("Resistance");
  await fields.getByLabel("Kind").selectOption("number");
  await fields.getByLabel("Unit").fill("Ω");
  await fields.getByLabel("Required").check();
  await fields.getByRole("button", { name: "Save" }).click();
  await expect(fields.getByRole("listitem").filter({ hasText: "resistance" })).toContainText(
    "Resistance",
  );

  // Three resistors, each typed the way it prints on the part (requirement 2.2).
  for (const resistor of resistors) {
    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("link", { name: "Parts" })
      .click();
    await page.getByRole("link", { name: "New part" }).click();
    await expect(page.getByRole("heading", { name: "New part" })).toBeVisible();

    await page.getByLabel("Category").selectOption({ label: category });
    await page.getByLabel("Name", { exact: true }).fill(resistor.name);
    await page.getByLabel("Resistance").fill(resistor.value);
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("heading", { name: resistor.name })).toBeVisible();
  }

  // The parts page is the search. On a phone the filters fold behind a toggle, so open it
  // when it's there before touching the controls (requirement 6.7).
  await page.getByRole("link", { name: "← Parts" }).click();
  await expect(page.getByRole("heading", { name: "Parts" })).toBeVisible();
  await openFilters(page);

  // Narrow to this category so its attribute filters appear.
  await page.getByLabel("Category").selectOption({ label: category });

  const results = page.getByRole("table", { name: "Parts" });
  const rowFor = (name: string) => results.getByRole("row").filter({ hasText: name });

  // All three show before any range is set.
  await expect(rowFor(r220.name)).toBeVisible();
  await expect(rowFor(r4k7.name)).toBeVisible();
  await expect(rowFor(r10k.name)).toBeVisible();

  // Filter 1k to 10k: the bounds are typed as they print, and read with the unit
  // (requirements 2.1, 2.2). 4k7 and 10k lie inside, 220R falls out (requirement 2.6).
  await page.getByLabel("Resistance at least").fill("1k");
  await page.getByLabel("Resistance at most").fill("10k");

  await expect(rowFor(r220.name)).toBeHidden();
  await expect(rowFor(r4k7.name)).toBeVisible();
  await expect(rowFor(r10k.name)).toBeVisible();

  // The order of the two remaining rows, top to bottom, reading each row's part name.
  const order = async () => {
    const cells = await results.getByRole("rowheader").allTextContents();
    return cells.map((cell) => cell.trim());
  };

  // Sort by resistance. A fresh column starts descending, so 10k comes before 4k7; the
  // header carries aria-sort so the order is announced (requirement 6.3).
  const resistanceHeader = () => results.getByRole("columnheader", { name: /Resistance/ });
  await results.getByRole("button", { name: /Sort by Resistance/ }).click();
  await expect(resistanceHeader()).toHaveAttribute("aria-sort", "descending");
  await expect.poll(order).toEqual([r10k.name, r4k7.name]);

  // Clicking the active column flips it to ascending: 4k7 then 10k.
  await results.getByRole("button", { name: /Sort by Resistance/ }).click();
  await expect(resistanceHeader()).toHaveAttribute("aria-sort", "ascending");
  await expect.poll(order).toEqual([r4k7.name, r10k.name]);

  // The whole search lives in the address (requirement 6.4): a reload restores it.
  await page.reload();
  await openFilters(page);
  await expect(page.getByLabel("Resistance at least")).toHaveValue("1k");
  await expect(page.getByLabel("Resistance at most")).toHaveValue("10k");
  await expect(resistanceHeader()).toHaveAttribute("aria-sort", "ascending");
  await expect(rowFor(r220.name)).toBeHidden();
  await expect.poll(order).toEqual([r4k7.name, r10k.name]);
});

/** On a phone the filter panel folds behind a toggle; open it when that toggle is shown. */
async function openFilters(page: import("@playwright/test").Page) {
  const toggle = page.getByRole("button", { name: "Show filters" });
  if (await toggle.isVisible()) await toggle.click();
}
