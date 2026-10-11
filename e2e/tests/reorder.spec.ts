import { expect, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";
import { LOGGED_OUT, OWNER } from "./owner";

/**
 * Minimum stock end to end (spec 24), on a guest's bench made for this run: the setting it
 * changes belongs to a workspace, and the other journeys share the owner's. A category gives
 * its parts a default minimum; a part under it shows on its page, on the dashboard and on the
 * reorder list while it has less; the workspace chooses what "has" means in Settings, which
 * the list then says; and the part's own minimum, once it is met, takes it off the list.
 */
test("watch a part's stock against a minimum, and choose what it is compared by", async ({
  browser,
  request,
}) => {
  test.slow();
  const stamp = `${test.info().project.name}-${Date.now()}`;
  const email = `reorder-${stamp}@example.com`;
  const category = `Inserts ${stamp}`;
  const part = `M3 insert ${stamp}`;

  const owner = await request.post("/api/auth/tokens", {
    data: { email: OWNER.email, password: OWNER.password },
  });
  const invited = await request.post("/api/auth/guests", {
    data: { email, days: 1 },
    headers: { Authorization: `Bearer ${(await owner.json()).token}` },
  });
  expect(invited.status()).toBe(201);
  const { password } = await invited.json();

  const context = await browser.newContext({ storageState: LOGGED_OUT });
  const page = await context.newPage();
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

  // A category whose parts should keep ten on hand.
  await page.goto("/categories");
  await page.getByLabel("Add a category").fill(category);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByRole("treeitem", { name: category }).click();
  const minimum = page.getByRole("textbox", { name: "Minimum stock of its parts" });
  await minimum.fill("10");
  await minimum.press("Enter");
  await expect(minimum).toHaveAccessibleDescription(/Set here/);

  // A part under it takes the default, and has none yet.
  await page.goto("/parts/new");
  await page.getByLabel("Category").selectOption({ label: category });
  await expect(page.getByRole("textbox", { name: "Minimum stock" })).toHaveAccessibleDescription(
    /take the category's default, 10/,
  );
  await page.getByLabel("Name", { exact: true }).fill(part);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: part })).toBeVisible();
  const identity = page.getByRole("region", { name: "Identity" });
  await expect(identity).toContainText(`(from ${category})`);
  await expect(identity).toContainText("Below minimum: 0 free, 10 missing.");

  // Four received: still six short.
  const stock = page.getByRole("region", { name: "Stock" });
  await stock.getByRole("button", { name: "Receive" }).click();
  const receive = page.getByRole("dialog", { name: "Receive stock" });
  await receive.getByRole("combobox", { name: "Location" }).selectOption({ index: 1 });
  await receive.getByRole("spinbutton", { name: "Quantity" }).fill("4");
  await receive.getByRole("button", { name: "Receive" }).click();
  await expect(receive).toBeHidden();
  await expect(identity).toContainText("Below minimum: 4 free, 6 missing.");

  // The dashboard says so, and the list shows what there is and what is missing.
  await page.goto("/");
  await expect(page.getByText("1 part is below its minimum stock.")).toBeVisible();
  await page.getByRole("link", { name: "See the reorder list" }).click();
  await expect(page.getByRole("heading", { name: "Reorder", level: 1 })).toBeVisible();
  const row = page.getByRole("row", { name: new RegExp(part) });
  await expect(row).toContainText(category);
  await expect(row).toContainText(`from ${category}`);
  await expect(row.getByRole("cell").nth(1)).toHaveText("4");
  await expect(row.getByRole("cell").nth(3)).toHaveText("6");
  await expect(page.getByText(/Compared against free stock/)).toBeVisible();
  await expectNoSidewaysScroll(page);

  // The workspace compares by total stock instead; the list says so, and a reload keeps it.
  await page.getByRole("link", { name: "Change this in Settings" }).click();
  await expect(page.getByRole("radio", { name: /^Free stock/ })).toBeChecked();
  await page.getByRole("radio", { name: /^Total stock/ }).click();
  await expect(page.getByText("Saved.")).toBeVisible();
  await expect(page.getByRole("radio", { name: /^Total stock/ })).toBeChecked();
  await expectNoSidewaysScroll(page);
  await page.goto("/reorder");
  await expect(page.getByText(/Compared against total stock/)).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "On hand" })).toBeVisible();
  await expect(row).toBeVisible();

  // The part's own minimum, met by what it has, takes it off the list.
  await row.getByRole("link", { name: part }).click();
  await identity.getByRole("button", { name: "Edit" }).click();
  await page.getByRole("textbox", { name: "Minimum stock" }).fill("3");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(identity).not.toContainText("Below minimum");
  await page.goto("/reorder");
  await expect(page.getByText(/Nothing to reorder/)).toBeVisible();
  await context.close();
});
