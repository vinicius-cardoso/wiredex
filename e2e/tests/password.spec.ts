import { expect, test } from "@playwright/test";
import { LOGGED_OUT, OWNER } from "./owner";

/**
 * Changing a password end to end (spec 23), on a guest account made for this run, so the
 * account every other journey logs in as keeps its password and its sessions. The guest is
 * logged in on a browser and on a "phone"; a wrong current password changes nothing; the
 * right one changes it, logs the phone out and leaves the browser in; and afterwards only
 * the new password logs in.
 */
test("change a password, logging the other devices out", async ({ browser, request }) => {
  const stamp = `${test.info().project.name}-${Date.now()}`;
  const email = `pw-${stamp}@example.com`;
  const next = `a new passphrase ${stamp}`;

  // The owner invites the guest over the API, as a phone app would: a bearer token, no cookie.
  const owner = await request.post("/api/auth/tokens", {
    data: { email: OWNER.email, password: OWNER.password },
  });
  const invited = await request.post("/api/auth/guests", {
    data: { email, days: 1 },
    headers: { Authorization: `Bearer ${(await owner.json()).token}` },
  });
  expect(invited.status()).toBe(201);
  const { password } = await invited.json();

  const phoneLogin = await request.post("/api/auth/tokens", { data: { email, password } });
  const phone = { Authorization: `Bearer ${(await phoneLogin.json()).token}` };

  const context = await browser.newContext({ storageState: LOGGED_OUT });
  const page = await context.newPage();
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

  await page.getByRole("button", { name: /^Account of / }).click();
  await page.getByRole("menuitem", { name: "Devices and password" }).click();
  const form = page.getByRole("form", { name: "Change your password" });
  await expect(page.getByRole("listitem")).toHaveCount(2);

  // A wrong current password: said so, nothing changed, the phone still in.
  await form.getByLabel("Current password").fill("not the password at all");
  await form.getByLabel("New password", { exact: true }).fill(next);
  await form.getByLabel("New password, again").fill(next);
  await form.getByRole("button", { name: "Change password" }).click();
  await expect(form.getByRole("alert")).toHaveText(
    "That isn't your current password. Nothing was changed.",
  );
  expect((await request.get("/api/auth/me", { headers: phone })).status()).toBe(200);

  // The right one: changed, the phone logged out, this browser still in.
  await form.getByLabel("Current password").fill(password);
  await form.getByRole("button", { name: "Change password" }).click();
  await expect(form.getByRole("status")).toHaveText(
    "Your password is changed. 1 other device was logged out.",
  );
  await expect(form.getByLabel("Current password")).toHaveValue("");
  await expect(page.getByRole("listitem")).toHaveCount(1);
  expect((await request.get("/api/auth/me", { headers: phone })).status()).toBe(401);

  // Only the new password logs in now.
  const old = await request.post("/api/auth/tokens", { data: { email, password } });
  expect(old.status()).toBe(401);
  const fresh = await request.post("/api/auth/tokens", { data: { email, password: next } });
  expect(fresh.status()).toBe(200);
  await context.close();
});
