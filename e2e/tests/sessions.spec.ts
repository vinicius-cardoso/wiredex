import { expect, test } from "@playwright/test";
import { OWNER } from "./owner";

test("the devices page lists this browser and can log another device out", async ({
  page,
  request,
}) => {
  // Another device: a "phone app" logs in through the token endpoint.
  const device = `Wiredex-E2E-Phone/${test.info().project.name}-${Date.now()}`;
  const login = await request.post("/api/auth/tokens", {
    data: { email: OWNER.email, password: OWNER.password },
    headers: { "User-Agent": device },
  });
  const bearer = { Authorization: `Bearer ${(await login.json()).token}` };

  await page.goto("/");
  await page.getByRole("link", { name: "Devices" }).click();

  await expect(page.getByRole("heading", { name: "Your devices" })).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: "This device" })).toHaveCount(1);
  const phone = page.getByRole("listitem").filter({ hasText: device });
  await expect(phone).toBeVisible();

  await page.getByRole("button", { name: `Log out ${device}` }).click();

  await expect(phone).toBeHidden();
  expect((await request.get("/api/auth/me", { headers: bearer })).status()).toBe(401);
});
