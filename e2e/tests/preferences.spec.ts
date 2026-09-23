import { expect, test } from "@playwright/test";

test.describe("theme", () => {
  test("an explicit choice applies at once and survives a reload", async ({ page }) => {
    await page.goto("/");

    await page.getByRole("button", { name: "Dark" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.getByRole("button", { name: "Dark" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  test("the saved theme applies before the app's JavaScript runs", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("wiredex.theme", "dark"));
    // Block the React bundle: only public/theme-init.js can set the theme now.
    await page.route("**/assets/*.js", (route) => route.abort());

    await page.goto("/");

    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  });

  test.describe("with a dark operating system", () => {
    test.use({ colorScheme: "dark" });

    test("system mode follows it", async ({ page }) => {
      await page.goto("/");

      await expect(page.getByRole("button", { name: "System" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    });
  });
});

test("the language switch translates the interface and is remembered", async ({ page }) => {
  await page.goto("/");

  await page.getByLabel("Language").selectOption("pt-BR");
  await expect(page.getByRole("heading", { name: "Painel" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "pt-BR");

  await page.reload();
  await expect(page.getByRole("heading", { name: "Painel" })).toBeVisible();
});
