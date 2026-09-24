import { spawnSync } from "node:child_process";
import { expect, test as setup } from "@playwright/test";
import { API_DIR, AUTH_FILE, OWNER } from "./owner";

setup("create the e2e account and log in", async ({ page }) => {
  // The same command the owner uses in production. A second run finds the account
  // already there (a reused local database), which is fine.
  const created = spawnSync(
    "uv",
    [
      "run",
      "wiredex",
      "users",
      "create",
      "--email",
      OWNER.email,
      "--name",
      OWNER.name,
      "--password-stdin",
    ],
    { cwd: API_DIR, input: `${OWNER.password}\n`, encoding: "utf8" },
  );
  const output = `${created.stdout}${created.stderr}`;
  expect(created.status === 0 || output.includes("already"), output).toBe(true);

  await page.goto("/login");
  await page.getByLabel("Email").fill(OWNER.email);
  await page.getByLabel("Password").fill(OWNER.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

  await page.context().storageState({ path: AUTH_FILE });
});
