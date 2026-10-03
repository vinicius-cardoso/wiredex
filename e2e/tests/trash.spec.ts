import { expect, type Locator, type Page, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";

/**
 * The trash end to end (16-soft-delete-and-trash): a part moved to the trash from its page is
 * gone from the parts list and listed in the trash; restored there, its page opens again from
 * the notice's link; moved again and deleted for good from its row, it is nowhere. A project
 * moved to the trash comes back with its revision. On a phone the trash page never scrolls
 * sideways (requirement 9.10, in the Pixel 7 project).
 *
 * It reuses the session auth.setup.ts saved, like every other journey, and never empties the
 * trash: the journeys of both projects share one workspace and run side by side, so emptying it
 * would take their records too; the page's tests cover it. The local database keeps what a run
 * creates, so every name carries a stamp, the worker's index in it too.
 */
test("move a part and a project to the trash, restore them, and delete the part for good", async ({
  page,
}) => {
  test.slow();
  const info = test.info();
  const stamp = `${info.project.name}-${info.workerIndex}-${Date.now()}`;
  const category = `Sensors ${stamp}`;
  const part = `Sensor ${stamp}`;
  const project = `Station ${stamp}`;
  const nav = page.getByRole("navigation", { name: "Main navigation" });

  // A part, defined through the pages.
  await page.goto("/categories");
  await page.getByLabel("Add a category").fill(category);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name: category })).toBeVisible();
  const partId = await createPart(page, category, part);

  // Moved to the trash from its page, after asking: the parts list no longer finds it (1.1,
  // 2.1, 9.1).
  await moveThePartToTheTrash(page);
  await searchParts(page, part);
  await expect(page.getByText("No part matches this search.")).toBeVisible();

  // The trash lists it, newest first, from the navigation's last link (9.2, 9.3).
  await nav.getByRole("link", { name: "Trash" }).click();
  await expect(page.getByRole("heading", { name: "Trash", level: 1 })).toBeVisible();
  const partRow = rowOf(page, part);
  await expect(partRow).toContainText("Part");
  await expectNoSidewaysScroll(page);

  // Restored: off the list, and the notice's link opens its page again (5.1, 5.2, 9.4).
  await partRow.getByRole("button", { name: `Restore ${part}` }).click();
  await expect(partRow).toHaveCount(0);
  await page.getByRole("link", { name: `Open ${part}` }).click();
  await expect(page.getByRole("heading", { name: part })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(`/parts/${partId}`);

  // Moved again, then deleted for good from its row after asking there: it is nowhere (6.1,
  // 9.5).
  await moveThePartToTheTrash(page);
  await nav.getByRole("link", { name: "Trash" }).click();
  await partRow.getByRole("button", { name: `Delete ${part} for good` }).click();
  await expect(
    partRow.getByRole("group", { name: `Delete ${part} for good? This can't be undone.` }),
  ).toBeVisible();
  await partRow.getByRole("button", { name: "Delete for good" }).click();
  await expect(partRow).toHaveCount(0);
  // Nowhere: not in the trash, not in the parts list, and its address is a 404.
  await nav.getByRole("link", { name: "Parts" }).click();
  await searchParts(page, part);
  await expect(page.getByText("No part matches this search.")).toBeVisible();
  expect((await page.request.get(`/api/catalog/parts/${partId}`)).status()).toBe(404);

  // A project, moved to the trash from its page and restored with its revision A (5.1).
  await page.goto("/projects/new");
  await page.getByLabel("Name", { exact: true }).fill(project);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: project })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Revision A", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Move to trash" }).click();
  await page.getByRole("button", { name: "Yes, move it" }).click();
  await expect(page.getByRole("heading", { name: "Projects", level: 1 })).toBeVisible();
  await nav.getByRole("link", { name: "Trash" }).click();
  const projectRow = rowOf(page, project);
  await expect(projectRow).toContainText("Project");

  // Narrowed by its name and its kind, the trash lists it alone; as a part, nothing matches,
  // and clearing the bar brings it back.
  await page.getByLabel("Search by name or detail").fill(project);
  await page.getByLabel("Kind").selectOption({ label: "Project" });
  await expect(page.getByRole("row")).toHaveCount(2);
  await expect(projectRow).toBeVisible();
  await page.getByLabel("Kind").selectOption({ label: "Part" });
  await expect(page.getByText("Nothing in the trash matches these filters.")).toBeVisible();
  await page.getByRole("button", { name: "Clear" }).click();
  await expect(projectRow).toBeVisible();

  await projectRow.getByRole("button", { name: `Restore ${project}` }).click();
  await page.getByRole("link", { name: `Open ${project}` }).click();
  await expect(page.getByRole("heading", { name: project })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Revision A", exact: true })).toBeVisible();
});

/** The trash's row for the record NAME, found by its row header as a screen reader does. */
function rowOf(page: Page, name: string): Locator {
  return page.getByRole("row").filter({ has: page.getByRole("rowheader", { name, exact: true }) });
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

/** Moves the part whose page is open to the trash, answering its question, onto the list. */
async function moveThePartToTheTrash(page: Page) {
  await page.getByRole("button", { name: "Move to trash", exact: true }).click();
  await expect(
    page.getByRole("group", {
      name: "Move this part to the trash? You can restore it from there.",
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Move part to trash" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Parts" })).toBeVisible();
}

/** Searches the parts list; on a phone its filters fold behind a toggle (6.7). */
async function searchParts(page: Page, text: string) {
  const showFilters = page.getByRole("button", { name: "Show filters" });
  if (await showFilters.isVisible()) await showFilters.click();
  await page.getByLabel("Search by name or number").fill(text);
}
