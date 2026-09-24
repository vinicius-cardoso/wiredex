import { spawnSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import { API_DIR, LOGGED_OUT } from "./owner";

test.use({ storageState: LOGGED_OUT });

/** `wiredex demo invite`, as the owner runs it; returns the password it prints once. */
function invite(email: string): string {
  const invited = spawnSync(
    "uv",
    ["run", "wiredex", "demo", "invite", "--email", email, "--name", "Friend", "--expires", "1d"],
    { cwd: API_DIR, encoding: "utf8" },
  );
  expect(invited.status, invited.stderr).toBe(0);
  const password = /Password, shown only now: (\S+)/.exec(invited.stdout)?.[1];
  if (!password) throw new Error(`no password in: ${invited.stdout}`);
  return password;
}

test("an invited guest logs in with the printed password and sees when access ends", async ({
  page,
}) => {
  const email = `guest-${test.info().project.name}-${Date.now()}@example.com`;
  const password = invite(email);

  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();

  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  const account = page.getByRole("region", { name: "Your account" });
  await expect(account).toContainText("Friend");
  await expect(account).toContainText("Guest until");
});
