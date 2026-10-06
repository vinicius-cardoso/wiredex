import { expect, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";

/**
 * The tour end to end: started from the account menu, it points at the navigation a stop at a
 * time, and left, it leaves the first things to do in a corner of the page, where opening the
 * palette ticks its mission. What it remembers is on the device, so every run starts unasked.
 */
test("look around the app, then tick a first thing to do", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Tour" })).toBeVisible();

  await page.getByRole("button", { name: /^Account of/ }).click();
  await page.getByRole("menuitem", { name: "Take the tour" }).click();
  const card = page.getByRole("dialog");
  await expect(card).toContainText("Welcome to Wiredex");
  // Taking it answers the dashboard's offer.
  await expect(page.getByRole("region", { name: "Tour" })).toHaveCount(0);

  await page.keyboard.press("Enter");
  await expect(card).toContainText("Parts and categories");
  await expect(card).toContainText("2 of 10");
  await card.getByRole("button", { name: "Next" }).click();
  await expect(card).toContainText("Locations");
  await expectNoSidewaysScroll(page);
  await page.keyboard.press("Escape");
  await expect(card).toBeHidden();

  const missions = page.getByRole("complementary", { name: "Getting started" });
  const palette = missions.getByRole("listitem").filter({ hasText: "Open the palette" });
  await expect(palette).toContainText("(to do)");
  await palette.getByRole("button", { name: "Show me" }).click();
  await expect(card).toContainText("Find anything");
  await card.getByRole("button", { name: "Got it" }).click();

  await page.keyboard.press("Control+k");
  await expect(page.getByRole("combobox")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(palette).toContainText("(done)");

  await missions.getByRole("button", { name: "Hide" }).click();
  await expect(missions).toBeHidden();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
  await expect(missions).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Tour" })).toHaveCount(0);
});
