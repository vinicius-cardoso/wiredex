import { expect, type Page } from "@playwright/test";

/**
 * The page is no wider than the screen: a wide table or line scrolls in its own box. Measured
 * against the device's width, not `innerWidth`: on a phone Chrome widens the layout viewport
 * to fit a page that overflows, and `innerWidth` grows with it, so that check can't fail.
 */
export async function expectNoSidewaysScroll(page: Page) {
  const screen = page.viewportSize()?.width ?? 0;
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth).toBeLessThanOrEqual(screen);
}
