import { expect, test } from "@playwright/test";
import { LOGGED_OUT, OWNER } from "./owner";

test.use({ storageState: LOGGED_OUT });

test("a visitor is sent to the login page and back after logging in", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Log in" })).toBeVisible();
  await expect(page).toHaveURL(/\/login\?redirect=/);
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeHidden();

  await page.getByLabel("Email").fill(OWNER.email);
  await page.getByLabel("Password").fill(OWNER.password);
  await page.getByRole("button", { name: "Log in" }).click();

  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page).toHaveURL(/\/$/);
});

test("wrong credentials are refused without saying which part was wrong", async ({ page }) => {
  await page.goto("/login");

  // An unknown email, so the e2e account's own failure counter never fills up.
  await page.getByLabel("Email").fill("nobody@example.com");
  await page.getByLabel("Password").fill("not a real password");
  await page.getByRole("button", { name: "Log in" }).click();

  await expect(page.getByRole("alert")).toHaveText("Wrong email or password.");
  await expect(page.getByRole("heading", { name: "Log in" })).toBeVisible();
});

test("the session cookie is out of the page's reach", async ({ page, context }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(OWNER.email);
  await page.getByLabel("Password").fill(OWNER.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

  const session = (await context.cookies()).find((c) => c.name === "__Host-wiredex_session");
  expect(session).toMatchObject({ httpOnly: true, secure: true, sameSite: "Lax", path: "/" });
  expect(await page.evaluate(() => document.cookie)).not.toContain("wiredex_session");
});
