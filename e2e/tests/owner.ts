import { fileURLToPath } from "node:url";
import { expect, type Page } from "@playwright/test";

/** The account every journey logs in as. auth.setup.ts creates it with the CLI. */
export const OWNER = {
  email: "e2e-owner@example.com",
  name: "E2E Owner",
  password: "e2e correct horse battery",
};

/** Cookies of a logged-in browser, saved once by auth.setup.ts and reused by every test. */
export const AUTH_FILE = fileURLToPath(new URL("../.auth/owner.json", import.meta.url));

export const API_DIR = fileURLToPath(new URL("../../apps/api", import.meta.url));

/** A browser that has never logged in. */
export const LOGGED_OUT = { cookies: [], origins: [] };

/** Logs in through the form, as a person would, and waits for the dashboard. */
export async function logIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(OWNER.email);
  await page.getByLabel("Password").fill(OWNER.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}
