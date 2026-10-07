import { expect, test } from "@playwright/test";
import { LOGGED_OUT } from "./owner";

/**
 * Sharing a demo end to end: the owner, from the account menu, invites a guest for three days
 * and is shown their login once. In a browser of their own the guest logs in with it to a
 * bench that holds the sample data and nothing of the owner's, and can't invite anyone. The
 * owner's session is the one auth.setup.ts saved; every run's guest has its own email.
 */
test("share a demo from the account menu, and log in as the guest", async ({ page, browser }) => {
  const stamp = `${test.info().project.name}-${Date.now()}`;
  const email = `shared-${stamp}@example.com`;
  // Something only the owner's bench holds, to look for from the guest's.
  const mine = `Owner location ${stamp}`;
  await page.goto("/locations");
  await page.getByLabel("Add a location").fill(mine);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name: mine })).toBeVisible();

  await page.getByRole("button", { name: /^Account of/ }).click();
  await page.getByRole("menuitem", { name: "Share a demo" }).click();
  const dialog = page.getByRole("dialog", { name: "Share a demo" });
  await dialog.getByLabel("Email").fill(email);
  await dialog.getByLabel("Name").fill("Friend");
  await dialog.getByLabel("Access for (days)").fill("3");
  await dialog.getByRole("button", { name: "Create the guest account" }).click();

  const done = page.getByRole("dialog", { name: "Friend can log in" });
  // Filling a bench with the samples takes a few seconds while every other journey writes.
  await expect(done).toContainText(email, { timeout: 30_000 });
  await expect(done).toContainText("The password is shown only now.");
  const password = (await done.locator("dd").nth(2).innerText()).trim();
  expect(password.length).toBeGreaterThanOrEqual(12);
  await done.getByRole("button", { name: "Close" }).click();
  await expect(done).toBeHidden();

  // The guest, in a browser that has never seen the owner's session.
  const context = await browser.newContext({ storageState: LOGGED_OUT });
  const guest = await context.newPage();
  await guest.goto("/login");
  await guest.getByLabel("Email").fill(email);
  await guest.getByLabel("Password").fill(password);
  await guest.getByRole("button", { name: "Log in" }).click();
  await expect(guest.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(guest.getByRole("region", { name: "Your account" })).toContainText("Guest until");

  // A bench of their own: the samples are there, and the owner's location is not.
  await guest.goto("/locations");
  await expect(guest.getByRole("treeitem").first()).toBeVisible();
  await expect(guest.getByRole("treeitem", { name: mine })).toHaveCount(0);

  // A guest can't pass the demo on.
  await guest.getByRole("button", { name: "Account of Friend" }).click();
  await expect(guest.getByRole("menuitem", { name: "Log out" })).toBeVisible();
  await expect(guest.getByRole("menuitem", { name: "Share a demo" })).toHaveCount(0);
  await context.close();
});
