import { expect, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";

/**
 * Part kinds end to end (spec 21): a category set to *Mechanical*; a part filed under it has no
 * package field on its form, and no pinout and no pin usage on its page, which says its kind;
 * the parts list narrows to mechanical parts, the choice kept in the address. Set back to
 * *Electronic*, the same part's page has its pinout section again.
 *
 * The refusals, a part with a pinout or on a net, are the API's and the components' tests': a
 * journey here would spend most of its time building a pinout. It reuses the session
 * auth.setup.ts saved and never logs out. Every name carries a stamp.
 */
test("mark a category mechanical and see its parts treated as such", async ({ page }) => {
  const info = test.info();
  const stamp = `${info.project.name}-${info.workerIndex}-${Date.now()}`;
  const category = `Hardware ${stamp}`;
  const part = `Standoff M3 ${stamp}`;

  await page.goto("/categories");
  await page.getByLabel("Add a category").fill(category);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByRole("treeitem", { name: category }).click();
  const panel = page.getByRole("region", { name: `The category ${category}` });
  const kind = panel.getByLabel("Kind");
  // Nothing set anywhere is electronic, which is what every category was (requirement 1.1).
  await expect(panel).toContainText("Inherited: electronic.");
  await kind.selectOption({ label: "Mechanical" });
  // The select follows the stored flag, so this waits until the change is saved.
  await expect(kind).toHaveValue("yes");

  // A mechanical part's form asks for no package (requirement 2.4).
  await page.goto("/parts");
  await page.getByRole("link", { name: "New part" }).click();
  await expect(page.getByLabel("Package")).toBeVisible();
  await page.getByLabel("Category").selectOption({ label: category });
  await expect(page.getByLabel("Package")).toBeHidden();
  await page.getByLabel("Name", { exact: true }).fill(part);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: part })).toBeVisible();
  const partPage = page.url();

  // Its page says its kind and has no pins to list or to wire (requirements 1.2, 2.3).
  const identity = page.getByRole("region", { name: "Identity" });
  await expect(identity).toContainText("Mechanical");
  await expect(page.getByRole("region", { name: "Stock" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Pinout", exact: true })).toBeHidden();
  await expect(page.getByRole("region", { name: "Pin usage" })).toBeHidden();
  await expectNoSidewaysScroll(page);

  // The parts list narrows by kind, and the address keeps the choice (requirement 3.1).
  await page.goto("/parts");
  // On a phone the filters fold behind a toggle.
  const toggle = page.getByRole("button", { name: "Show filters" });
  const search = page.getByRole("searchbox", { name: "Search by name or number" });
  // Whichever the page shows once it has rendered: asked at once, neither is there yet.
  await expect(toggle.or(search).first()).toBeVisible();
  if (await toggle.isVisible()) await toggle.click();
  await search.fill(stamp);
  await page.getByLabel("Kind").selectOption({ label: "Mechanical" });
  await expect(page).toHaveURL(/[?&]kind=mechanical/);
  await expect(page.getByRole("link", { name: part })).toBeVisible();
  await page.getByLabel("Kind").selectOption({ label: "Electronic" });
  await expect(page.getByRole("link", { name: part })).toBeHidden();
  await expectNoSidewaysScroll(page);

  // Electronic again, which is never refused (requirement 1.4), and the pinout is back.
  await page.goto("/categories");
  await page.getByRole("treeitem", { name: category }).click();
  await kind.selectOption({ label: "Electronic" });
  await expect(kind).toHaveValue("no");
  await page.goto(partPage);
  await expect(page.getByRole("region", { name: "Pinout", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Identity" })).toContainText("Electronic");
});
