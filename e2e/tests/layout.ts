import { expect, type Page } from "@playwright/test";
/**
 * The page is no wider than the screen: a wide table or line scrolls in its own box. Measured
 * against the device's width, not `innerWidth`: on a phone Chrome widens the layout viewport
 * to fit a page that overflows, and `innerWidth` grows with it, so that check can't fail.
 *
 * A detail block's table must fit its frame too. A frame scrolls inside itself, so a table that
 * stopped reflowing into cards on a phone would leave the document the screen's width and pass
 * the first check; only the frames' own widths show it.
 */
export async function expectNoSidewaysScroll(page: Page) {
  const screen = page.viewportSize()?.width ?? 0;
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth).toBeLessThanOrEqual(screen);
  const wideFrames = await page.evaluate(() =>
    Array.from(document.querySelectorAll<HTMLElement>("main [data-stack]"))
      .filter((frame) => frame.scrollWidth > frame.clientWidth)
      .map((frame) => {
        const name = frame.closest("[aria-labelledby]")?.getAttribute("aria-labelledby");
        const block = name ? document.getElementById(name)?.textContent : null;
        return `${block ?? "a frame"}: ${frame.scrollWidth}/${frame.clientWidth}`;
      }),
  );
  expect(wideFrames, "tables wider than their frames").toEqual([]);
}
