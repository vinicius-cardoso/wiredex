import { expect, test } from "@playwright/test";

test("the dashboard opens inside the app shell", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
});

test("the footer shows the web version and the version the API reports", async ({ page }) => {
  await page.goto("/");

  const footer = page.getByRole("contentinfo");
  await expect(footer).toContainText(/Wiredex v\d+\.\d+\.\d+/);
  await expect(footer).toContainText(/API v\d+\.\d+\.\d+/);
});

test("the API is ready behind the same origin", async ({ request }) => {
  const response = await request.get("/api/health/ready");

  expect(response.status()).toBe(200);
  expect(await response.json()).toEqual({ status: "ready", database: "up" });
});

test("unknown paths show a not-found page with a way back", async ({ page }) => {
  await page.goto("/no/such/page");

  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await page.getByRole("link", { name: "Back to the dashboard" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
});

test("the icons the page links to are served", async ({ page, request }) => {
  await page.goto("/");

  const links = page.locator(
    'link[rel="icon"], link[rel="apple-touch-icon"], link[rel="manifest"]',
  );
  const hrefs = await links.evaluateAll((elements) =>
    elements.map((element) => element.getAttribute("href") ?? ""),
  );
  expect(hrefs).toEqual(
    expect.arrayContaining([
      "/favicon.svg",
      "/favicon.ico",
      "/apple-touch-icon.png",
      "/site.webmanifest",
    ]),
  );
  for (const href of hrefs) {
    expect((await request.get(href)).status(), href).toBe(200);
  }
});
