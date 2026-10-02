import { expect, type Page, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";

/**
 * History end to end (17-history): a part defined and renamed twice, its History read on its page
 * with each rename's name before and after, the version before the second rename restored, the
 * page showing that name again, and the activity page holding the restore, by its own record.
 *
 * It reuses the session auth.setup.ts saved, like every other journey. The local database keeps
 * what a run creates, so every name carries a stamp, the worker's index in it too; the activity
 * page lists every journey's changes, so the part's are found by its stamped names.
 */
test("rename a part, read its history, restore a version and find it in the activity", async ({
  page,
}) => {
  test.slow();
  const info = test.info();
  const stamp = `${info.project.name}-${info.workerIndex}-${Date.now()}`;
  const category = `Sensors ${stamp}`;
  const first = `Sensor ${stamp}`;
  const second = `Sensor A ${stamp}`;
  const third = `Sensor B ${stamp}`;

  await page.goto("/categories");
  await page.getByLabel("Add a category").fill(category);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name: category })).toBeVisible();
  await page.goto("/parts");
  await page.getByRole("link", { name: "New part" }).click();
  await page.getByLabel("Category").selectOption({ label: category });
  await page.getByLabel("Name", { exact: true }).fill(first);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: first })).toBeVisible();

  // Renamed twice, each a change of its own (requirement 1.1).
  await rename(page, second);
  await rename(page, third);

  // Its History, opened on its page: the newest change first, each rename's name before and
  // after, then its creation (requirements 3.1, 7.3).
  const history = page.getByRole("region", { name: "History" });
  await history.getByRole("button", { name: "Show history" }).click();
  const changes = history.getByRole("list", { name: "Changes" }).getByRole("listitem");
  const newest = changes.first();
  await expect(newest).toContainText("Edited");
  await expect(newest).toContainText(second);
  await expect(newest).toContainText(third);
  await expect(changes.filter({ hasText: "Created" })).toHaveCount(1);

  // The version before the second rename put back, as a new change (requirements 4.1, 4.2).
  await newest.getByRole("button", { name: "Restore the version before this change" }).click();
  await newest.getByRole("button", { name: "Restore", exact: true }).click();
  await expect(page.getByRole("heading", { name: second })).toBeVisible();
  await expect(changes.first()).toContainText("Restored an earlier version");

  // The activity page holds the restore, linking to the part (requirement 7.2).
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Activity" })
    .click();
  await expect(page.getByRole("heading", { name: "Activity", level: 1 })).toBeVisible();
  const restore = page
    .getByRole("list", { name: "Changes" })
    .getByRole("listitem")
    .filter({ hasText: "Restored an earlier version" })
    .filter({ has: page.getByRole("link", { name: `Part ${second}` }) });
  await expect(restore).toHaveCount(1);
  await expectNoSidewaysScroll(page);
  await restore.getByRole("link", { name: `Part ${second}` }).click();
  await expect(page.getByRole("heading", { name: second })).toBeVisible();
});

/** Renames the part whose page is open, through its edit form. */
async function rename(page: Page, name: string) {
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  const field = page.getByLabel("Name", { exact: true });
  await field.fill(name);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
}
