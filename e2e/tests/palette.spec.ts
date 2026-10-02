import { expect, type Page, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";

/**
 * The command palette end to end (19-command-palette): a part and its category defined, then,
 * from the dashboard, the palette opened with Ctrl K (the header's button on a phone), the part
 * typed, found and opened with Enter; the category found and its parts opened; a command typed
 * and run; and Escape handing focus back to the button that opened it (requirements 3.1, 3.2,
 * 3.4, 4.2, 4.4, 5.3).
 *
 * It reuses the session auth.setup.ts saved, like every other journey. The local database keeps
 * what a run creates, so every name carries a stamp, the project and the worker in it too, and the
 * palette is given the whole stamped name: no other run's record holds it.
 */
test("open the palette, find a part and a category, run a command", async ({ page }) => {
  test.slow();
  const info = test.info();
  const stamp = `${info.project.name}-${info.workerIndex}-${Date.now()}`;
  const category = `Palette sensors ${stamp}`;
  const part = `Palette sensor ${stamp}`;
  const phone = info.project.name === "mobile";

  await page.goto("/categories");
  await page.getByLabel("Add a category").fill(category);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name: category })).toBeVisible();
  await page.goto("/parts");
  await page.getByRole("link", { name: "New part" }).click();
  await page.getByLabel("Category").selectOption({ label: category });
  await page.getByLabel("Name", { exact: true }).fill(part);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: part })).toBeVisible();

  // From the dashboard: the part, typed whole, is the first choice, and Enter opens its page.
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
  let palette = await openPalette(page, phone);
  await page.keyboard.type(part);
  const parts = palette.getByRole("group", { name: "Parts" });
  await expect(parts.getByRole("option", { name: part })).toHaveAttribute("aria-selected", "true");
  await expectNoSidewaysScroll(page);
  await page.keyboard.press("Enter");
  await expect(palette).toBeHidden();
  await expect(page.getByRole("heading", { name: part, level: 1 })).toBeVisible();

  // The category opens the parts filed under it, the part among them (decision 8).
  palette = await openPalette(page, phone);
  await page.keyboard.type(category);
  const categories = palette.getByRole("group", { name: "Categories" });
  await expect(categories.getByRole("option", { name: category })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/parts\?category=/);
  await expect(page.getByRole("link", { name: part })).toBeVisible();

  // A command, typed in part and run with Enter.
  palette = await openPalette(page, phone);
  await page.keyboard.type("trash");
  await expect(palette.getByRole("option", { name: "Go to the Trash" })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Trash", level: 1 })).toBeVisible();

  // Escape closes it and hands focus back to the button that opened it (requirement 3.4).
  const search = page.getByRole("button", { name: "Search", exact: true });
  await search.click();
  await expect(page.getByRole("dialog", { name: "Search and commands" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Search and commands" })).toBeHidden();
  await expect(search).toBeFocused();
});

/**
 * Opens the palette as the owner would here: Ctrl K at a desk, the header's button on a phone.
 * Either way the box has focus once it is open.
 */
async function openPalette(page: Page, phone: boolean) {
  if (phone) await page.getByRole("button", { name: "Search", exact: true }).click();
  else await page.keyboard.press("Control+KeyK");
  const palette = page.getByRole("dialog", { name: "Search and commands" });
  await expect(palette.getByRole("combobox", { name: "Search Wiredex" })).toBeFocused();
  return palette;
}
