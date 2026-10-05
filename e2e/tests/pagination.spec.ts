import { expect, type Locator, type Page, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";

/**
 * A list paged by number end to end: thirty parts, put in through the API, are paged at 25 on
 * the parts list. The page and its size live in the address, so Next adds a history entry that
 * Back and Forward walk; a new sort goes back to page 1 at the size chosen; an address past the
 * end is replaced by the last page. The activity pages the same thirty changes with the same
 * bar. On a laptop only the table scrolls, inside its frame, and the bar stays put under it; on
 * a phone nothing scrolls sideways.
 *
 * It reuses the session auth.setup.ts saved and never clears anything: both projects share one
 * workspace and run side by side, so every name carries a stamp and every list is narrowed to
 * it.
 */
test("page through the parts and the activity, and come back with Back", async ({ page }) => {
  test.slow();
  const info = test.info();
  const stamp = `${info.project.name}-${info.workerIndex}-${Date.now()}`;
  const text = `Paging part ${stamp}`;
  const desktop = info.project.name === "desktop";

  // Thirty parts, named so they sort 01 to 30.
  await page.goto("/");
  await createParts(page, `Paging category ${stamp}`, text, 30);

  await page.goto(`/parts?${new URLSearchParams({ text, sort: "name", dir: "asc" })}`);
  const bar = page.getByRole("navigation", { name: "Pages of the parts list" });
  const table = page.getByRole("table", { name: "Parts" });
  await expect(bar.getByText("1–30 of 30")).toBeVisible();

  // 25 a page: the size joins the address, and page 1 holds parts 01 to 25.
  await bar.getByLabel("Per page").selectOption("25");
  await expect(bar.getByText("1–25 of 30")).toBeVisible();
  expect(addressOf(page).get("size")).toBe("25");
  expect(addressOf(page).has("page")).toBe(false);
  await expect(table.getByRole("row")).toHaveCount(26);
  await expect(firstPart(table)).toHaveText(`${text} 01`);

  if (desktop) await expectOnlyTheTableScrolls(page, table.locator(".."), bar);
  else await expectNoSidewaysScroll(page);

  // Next page pushes page 2: parts 26 to 30.
  await bar.getByRole("button", { name: "Next page" }).click();
  await expect(bar.getByText("26–30 of 30")).toBeVisible();
  expect(addressOf(page).get("page")).toBe("2");
  expect(addressOf(page).get("size")).toBe("25");
  await expect(bar.getByRole("button", { name: "Page 2" })).toHaveAttribute("aria-current", "page");
  await expect(table.getByRole("row")).toHaveCount(6);
  await expect(firstPart(table)).toHaveText(`${text} 26`);
  if (!desktop) await expectNoSidewaysScroll(page);

  // Back walks to page 1, Forward to page 2 again.
  await page.goBack();
  await expect(firstPart(table)).toHaveText(`${text} 01`);
  expect(addressOf(page).has("page")).toBe(false);
  expect(addressOf(page).get("size")).toBe("25");
  await page.goForward();
  await expect(firstPart(table)).toHaveText(`${text} 26`);
  expect(addressOf(page).get("page")).toBe("2");

  // A new sort starts again at page 1, at the size chosen.
  await table.getByRole("button", { name: "Sort by name (ascending)" }).click();
  await expect(firstPart(table)).toHaveText(`${text} 30`);
  await expect(bar.getByText("1–25 of 30")).toBeVisible();
  expect(addressOf(page).has("page")).toBe(false);
  expect(addressOf(page).has("dir")).toBe(false);
  expect(addressOf(page).get("size")).toBe("25");

  // An address past the end opens the last page and takes its place: Back then skips it.
  await page.goto(
    `/parts?${new URLSearchParams({ text, sort: "name", dir: "asc", page: "9", size: "25" })}`,
  );
  await expect(bar.getByText("26–30 of 30")).toBeVisible();
  await expect(firstPart(table)).toHaveText(`${text} 26`);
  await expect.poll(() => addressOf(page).get("page")).toBe("2");
  await page.goBack();
  await expect(firstPart(table)).toHaveText(`${text} 30`);
  expect(addressOf(page).has("page")).toBe(false);

  // The activity pages the thirty parts' creations with the same bar.
  await page.goto(`/activity?${new URLSearchParams({ q: text, size: "25" })}`);
  const activityBar = page.getByRole("navigation", { name: "Pages of the activity" });
  const changes = page.getByRole("list", { name: "Changes" }).locator(":scope > li");
  await expect(activityBar.getByText("1–25 of 30")).toBeVisible();
  await expect(changes).toHaveCount(25);
  await activityBar.getByRole("button", { name: "Last page" }).click();
  await expect(activityBar.getByText("26–30 of 30")).toBeVisible();
  await expect(changes).toHaveCount(5);
  expect(addressOf(page).get("page")).toBe("2");
  if (!desktop) await expectNoSidewaysScroll(page);
});

/** The page's address as search params. */
function addressOf(page: Page): URLSearchParams {
  return new URL(page.url()).searchParams;
}

/** The name of the first part the table lists, read off its row header. */
function firstPart(table: Locator): Locator {
  return table.getByRole("rowheader").first();
}

/**
 * Puts a category and COUNT parts in it through the API, as the page would: the CSRF cookie
 * echoed in its header. The parts are named PREFIX 01, 02 and so on.
 */
async function createParts(page: Page, category: string, prefix: string, count: number) {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === "__Host-wiredex_csrf")?.value;
  if (!csrf) throw new Error("no CSRF cookie: the saved session isn't loaded");
  const headers = { "X-CSRF-Token": csrf };
  const created = await page.request.post("/api/catalog/categories", {
    data: { name: category },
    headers,
  });
  expect(created.status()).toBe(201);
  const { id } = (await created.json()) as { id: string };
  for (let number = 1; number <= count; number += 1) {
    const name = `${prefix} ${String(number).padStart(2, "0")}`;
    const part = await page.request.post("/api/catalog/parts", {
      data: { category_id: id, name },
      headers,
    });
    expect(part.status(), name).toBe(201);
  }
}

/**
 * On a laptop the list page is the screen: `main` and the document don't scroll, the table
 * scrolls inside its frame, and the bar sits under it, inside `main`, without moving when the
 * table does.
 */
async function expectOnlyTheTableScrolls(page: Page, frame: Locator, bar: Locator) {
  const main = page.getByRole("main");
  const mainSize = await main.evaluate((element) => ({
    scroll: element.scrollHeight,
    client: element.clientHeight,
  }));
  expect(mainSize.scroll, "main doesn't scroll").toBe(mainSize.client);
  const frameSize = await frame.evaluate((element) => ({
    scroll: element.scrollHeight,
    client: element.clientHeight,
  }));
  expect(frameSize.scroll, "the table scrolls in its frame").toBeGreaterThan(frameSize.client);

  const mainBox = await main.boundingBox();
  const before = await bar.boundingBox();
  if (!mainBox || !before) throw new Error("the list isn't laid out");
  expect(before.y + before.height).toBeLessThanOrEqual(mainBox.y + mainBox.height);

  await frame.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await expect.poll(() => frame.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  expect(await bar.boundingBox(), "the bar stays put").toEqual(before);

  const heights = await page.evaluate(() => ({
    document: document.documentElement.scrollHeight,
    screen: window.innerHeight,
  }));
  expect(heights.document, "the document doesn't scroll").toBe(heights.screen);
}
