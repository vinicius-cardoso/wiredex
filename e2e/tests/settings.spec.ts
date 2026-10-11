import { expect, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";
import { LOGGED_OUT, OWNER } from "./owner";

/**
 * The workspace's settings end to end (spec 25), on a guest's bench made for this run: the
 * settings are a workspace's, and the other journeys share the owner's. A new code prefix codes
 * the next location; a date format writes the devices page's dates; a default minimum puts the
 * bench's parts on the reorder list, said to be the workspace's default; and a trash retention
 * is said on the trash page. Each survives a reload, since the server keeps them.
 */
test("change the workspace's settings and see each one take effect", async ({
  browser,
  request,
}) => {
  test.slow();
  const stamp = `${test.info().project.name}-${Date.now()}`;
  const email = `settings-${stamp}@example.com`;
  const shelf = `Shelf ${stamp}`;

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

  await page.getByRole("button", { name: /^Account of / }).click();
  await page.getByRole("menuitem", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
  // The theme and the language stay in the header.
  await expect(page.getByRole("button", { name: /^Theme: / })).toBeVisible();

  const prefix = page.getByRole("textbox", { name: "Code prefix" });
  await prefix.fill("lab");
  await prefix.press("Enter");
  await expect(prefix).toHaveAccessibleDescription(/LAB-L-0007/);
  await page.getByRole("radio", { name: /^Year first \(ISO\)/ }).click();
  await expect(page.getByRole("radio", { name: /^Year first \(ISO\)/ })).toBeChecked();
  const minimum = page.getByRole("textbox", { name: "Default minimum stock" });
  await minimum.fill("1000");
  await minimum.press("Enter");
  await expect(page.getByText("Saved.")).toBeVisible();
  await page
    .getByRole("combobox", { name: "Keep what is moved to the trash for" })
    .selectOption({ label: "7 days" });
  await expect(page.getByText(/longer than 7 days is deleted for good/)).toBeVisible();
  await expectNoSidewaysScroll(page);

  // Kept by the server: a reload reads them back.
  await page.reload();
  await expect(page.getByRole("textbox", { name: "Code prefix" })).toHaveValue("LAB");
  await expect(page.getByRole("radio", { name: /^Year first \(ISO\)/ })).toBeChecked();
  await expect(page.getByRole("textbox", { name: "Default minimum stock" })).toHaveValue("1000");

  // A new location takes the prefix; the bench's own keep theirs.
  await page.goto("/locations");
  await page.getByLabel("Add a location").fill(shelf);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name: new RegExp(shelf) })).toContainText(
    /LAB-L-\d{4}/,
  );

  // Dates are written year first.
  await page.goto("/sessions");
  await expect(page.getByRole("listitem").first()).toContainText(/\d{4}-\d{2}-\d{2} \d{2}:\d{2}/);

  // Every part of the bench is held to the workspace's default, and below it.
  await page.goto("/reorder");
  const table = page.getByRole("table", { name: "Parts below their minimum stock" });
  await expect(table.getByText("workspace default").first()).toBeVisible();

  // The trash says how long it keeps things.
  await page.goto("/trash");
  await expect(page.getByText(/Kept for 7 days, then deleted for good each night\./)).toBeVisible();
  await context.close();
});
