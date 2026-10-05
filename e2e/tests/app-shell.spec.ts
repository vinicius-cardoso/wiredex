import { expect, type Page, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";

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

/** The laptop screens the layout is checked at; on each one the shell is the screen. */
const LAPTOPS = [
  { width: 1366, height: 768 },
  { width: 1440, height: 810 },
  { width: 1920, height: 930 },
];

/**
 * Creates a project whose description runs to sixty lines, so its page is taller than any
 * laptop screen, and waits for the open revision's last section, its files, to be shown.
 */
async function openTallProject(page: Page) {
  const info = test.info();
  const name = `Tall project ${info.project.name}-${info.workerIndex}-${Date.now()}`;
  const notes = Array.from({ length: 60 }, (_, line) => `Build note ${line + 1}.`).join("\n");
  await page.goto("/projects/new");
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel("Description").fill(notes);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  const revision = page.getByRole("region", { name: "Revision A", exact: true });
  await expect(revision.getByRole("region", { name: "Files" })).toBeVisible();
}

/**
 * On a laptop only `main` scrolls; the page itself never does. The visually hidden texts far
 * down a tall page (a table's caption, a file input) are placed absolutely, and before `main`
 * was positioned they escaped it and stretched the document: the footer ended mid-screen over
 * an empty band, under a second scrollbar.
 */
test("on a laptop only the main area scrolls, never the page itself", async ({ page }) => {
  test.skip(test.info().project.name === "mobile", "the fixed shell is for laptop screens");
  await openTallProject(page);
  const main = page.getByRole("main");
  for (const laptop of LAPTOPS) {
    const size = `${laptop.width}x${laptop.height}`;
    await page.setViewportSize(laptop);
    const overflow = await main.evaluate((element) => element.scrollHeight - element.clientHeight);
    expect(overflow, `${size}: taller than the screen`).toBeGreaterThan(laptop.height);
    await main.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
    });
    const heights = await page.evaluate(() => ({
      document: document.documentElement.scrollHeight,
      screen: window.innerHeight,
    }));
    expect(heights.document, `${size}: the document doesn't scroll`).toBe(heights.screen);
    const footer = await page.getByRole("contentinfo").boundingBox();
    expect(footer && Math.round(footer.y + footer.height), `${size}: footer at the bottom`).toBe(
      laptop.height,
    );
  }
});

/** Below a laptop's width the page scrolls as a whole, as it always has, and never sideways. */
test("on a phone the page scrolls as a whole, and never sideways", async ({ page }) => {
  test.skip(test.info().project.name !== "mobile", "below laptop widths only");
  await openTallProject(page);
  const sizes = await page.evaluate(() => {
    const main = document.querySelector("main");
    return {
      document: document.documentElement.scrollHeight,
      screen: window.innerHeight,
      mainOverflow: main ? main.scrollHeight - main.clientHeight : Number.NaN,
    };
  });
  expect(sizes.document).toBeGreaterThan(sizes.screen);
  expect(sizes.mainOverflow).toBe(0);
  await expectNoSidewaysScroll(page);
});

/** A detail page is a grid of blocks: on a laptop a project's About and Photos share a row. */
test("on a laptop a project's About and Photos sit side by side", async ({ page }) => {
  test.skip(test.info().project.name === "mobile", "a laptop layout");
  await page.setViewportSize({ width: 1440, height: 810 });
  await openTallProject(page);
  const about = await page.getByRole("region", { name: "About" }).boundingBox();
  const photos = await page.getByRole("region", { name: "Photos" }).boundingBox();
  if (!about || !photos) throw new Error("the blocks aren't laid out");
  expect(Math.abs(photos.y - about.y)).toBeLessThanOrEqual(1);
  expect(photos.x).toBeGreaterThanOrEqual(about.x + about.width - 1);
});

/** On a phone the blocks stack in one column, in reading order, and nothing scrolls sideways. */
test("on a phone a project's Photos sit below its About", async ({ page }) => {
  test.skip(test.info().project.name !== "mobile", "a phone layout");
  await openTallProject(page);
  const about = await page.getByRole("region", { name: "About" }).boundingBox();
  const photos = await page.getByRole("region", { name: "Photos" }).boundingBox();
  if (!about || !photos) throw new Error("the blocks aren't laid out");
  expect(photos.y).toBeGreaterThanOrEqual(about.y + about.height);
  expect(Math.abs(photos.x - about.x)).toBeLessThanOrEqual(1);
  await expectNoSidewaysScroll(page);
});

/**
 * On a wide screen the content starts at the left edge, under the logo and behind the same
 * small gutter, and takes the full width: no centred column leaves an empty band beside it.
 */
test("on a wide screen the content starts at the left edge and takes the full width", async ({
  page,
}) => {
  test.skip(test.info().project.name === "mobile", "a wide-screen layout");
  await page.setViewportSize({ width: 1920, height: 930 });
  await page.goto("/parts");
  const title = page.getByRole("heading", { name: "Parts", level: 1 });
  await expect(title).toBeVisible();
  const logo = await page
    .getByRole("banner")
    .getByRole("link", { name: "Wiredex", exact: true })
    .boundingBox();
  const heading = await title.boundingBox();
  const filters = await page.getByRole("main").locator("search").boundingBox();
  const version = await page
    .getByRole("contentinfo")
    .getByText(/^Wiredex v/)
    .boundingBox();
  if (!logo || !heading || !filters || !version) throw new Error("the shell isn't laid out");
  expect(logo.x).toBeLessThanOrEqual(24);
  expect(heading.x).toBeCloseTo(logo.x, 0);
  expect(version.x).toBeCloseTo(logo.x, 0);
  expect(filters.x + filters.width).toBeGreaterThanOrEqual(1920 - 24);
});
