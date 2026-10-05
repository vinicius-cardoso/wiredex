import { expect, type Locator, type Page, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";

/**
 * The dashboard end to end (18-dashboard): 60 of a resistor received, revision A of a project
 * needing 50 of it and reserving them, then forked into B, a draft needing 50 more with only 10
 * left available. The dashboard shows the resistor tied up by A, B short of 40, and the
 * workspace's newest changes as the feed answers them. Cancelling A's reservation, through the
 * link the dashboard gives, frees the resistor and covers B, and the dashboard says so the next
 * time it is shown (requirements 1.1, 1.4, 2.1, 3.1, 3.2, 5.1, 5.3, 5.6).
 *
 * It reuses the session auth.setup.ts saved, like every other journey. The local database keeps
 * every run's projects, and the dashboard lists drafts by project name and ties by part name, 20
 * at most, so every name carries a stamp that falls as time passes: this run's sort before every
 * earlier one's. The project and worker in it keep two runs side by side apart.
 */
test("see parts tied up in builds, drafts short of parts and the newest changes", async ({
  page,
}) => {
  test.slow();
  const info = test.info();
  const stamp = `${10 ** 13 - Date.now()}-${info.project.name}-${info.workerIndex}`;
  const drawer = `Drawer ${stamp}`;
  const passives = `Passives ${stamp}`;
  const resistor = `Resistor ${stamp}`;
  // A leading digit sorts the project before every other journey's, all of them named in words.
  const project = `0 Dashboard ${stamp}`;

  await page.goto("/locations");
  await page.getByLabel("Add a location").fill(drawer);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name: drawer })).toBeVisible();

  // A fresh root category is lot-counted, so the resistor takes a loose receive.
  await page.goto("/categories");
  await page.getByLabel("Add a category").fill(passives);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name: passives })).toBeVisible();
  const resistorId = await createPart(page, passives, resistor);
  await receive(page, drawer, 60);

  // Revision A needs 50 and reserves them: 50 tied up, 10 left available.
  await page.goto("/projects");
  await page.getByRole("link", { name: "New project" }).click();
  await page.getByLabel("Name", { exact: true }).fill(project);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: project })).toBeVisible();
  const revisionA = page.getByRole("region", { name: "Revision A", exact: true });
  const bom = revisionA.getByRole("region", { name: "Bill of materials" });
  const newLine = bom.getByRole("row", { name: "New line" });
  await newLine.getByRole("textbox", { name: "Designators" }).focus();
  await page.keyboard.press("Tab");
  await pickPart(page, newLine.getByRole("combobox", { name: "Part" }), resistor);
  await page.keyboard.press("Tab");
  await expect(newLine.getByRole("spinbutton", { name: "Quantity" })).toBeFocused();
  await page.keyboard.type("50");
  await page.keyboard.press("Enter");
  const lines = bom.getByRole("table", { name: "Lines of the bill of materials" });
  await expect(
    lineRow(lines, resistor).getByRole("cell", { name: "50", exact: true }),
  ).toBeVisible();

  await revisionA.getByRole("button", { name: "Reserve parts" }).click();
  const reserve = page.getByRole("dialog", { name: "Reserve parts" });
  await reserve.getByRole("button", { name: "Reserve", exact: true }).click();
  await expect(reserve).toBeHidden();
  await expect(revisionA.getByText("Reserved", { exact: true })).toBeVisible();

  // B, forked from A, is a draft with the same BOM: 50 needed, 10 available, so 40 short.
  await revisionA.getByRole("button", { name: "Fork", exact: true }).click();
  const fork = page.getByRole("dialog", { name: /Fork revision A/ });
  await fork.getByRole("button", { name: "Fork", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Revision B", exact: true })).toBeVisible();

  // The dashboard, from the navigation. Every journey writes beside this one, so the newest
  // changes are whatever the feed answered when the dashboard asked: the panel shows those.
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  const recent = page.waitForResponse((response) =>
    response.url().includes("/api/history?page_size=10"),
  );
  await nav.getByRole("link", { name: "Dashboard" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
  const feed = (await (await recent).json()) as { changes: { record: { label: string | null } }[] };
  // This journey just wrote, so the feed holds something, and never more than it was asked for.
  expect(feed.changes.length).toBeGreaterThan(0);
  expect(feed.changes.length).toBeLessThanOrEqual(10);

  // Tied up in builds: the resistor, linking to its page, 50 reserved by A (requirement 1.1).
  const tiedUp = page.getByRole("region", { name: "Tied up in builds" });
  const resistorLink = tiedUp.getByRole("link", { name: resistor, exact: true });
  await expect(resistorLink).toHaveAttribute("href", `/parts/${resistorId}`);
  const held = tiedUp
    .getByRole("listitem")
    .filter({ has: page.getByRole("link", { name: resistor, exact: true }) });
  await expect(held).toContainText("50 reserved");
  const heldByA = held.getByRole("link", { name: `${project} · A`, exact: true });
  await expect(heldByA).toBeVisible();

  // Shortages: B, linking to its revision, short of 40 with 50 needed and 10 in stock (2.1).
  const shortages = page.getByRole("region", { name: "Shortages" });
  const shortB = shortages
    .getByRole("listitem")
    .filter({ has: page.getByRole("link", { name: `${project} · B`, exact: true }) });
  await expect(shortB).toContainText("1 part missing");
  const shortResistor = shortB
    .getByRole("listitem")
    .filter({ has: page.getByRole("link", { name: resistor, exact: true }) });
  await expect(shortResistor).toContainText("40 short needs 50, 10 in stock");
  await expect(shortages.getByRole("link", { name: `${project} · A`, exact: true })).toHaveCount(0);

  // Recent activity: the feed's changes, newest first, and a link to the whole of it (3.1, 3.2).
  const activity = page.getByRole("region", { name: "Recent activity" });
  const changes = activity.getByRole("list", { name: "Recent changes" }).getByRole("listitem");
  await expect(changes).toHaveCount(feed.changes.length);
  await expect(changes.first()).toContainText(feed.changes[0]?.record.label ?? "unnamed");
  await expect(activity.getByRole("link", { name: "All activity" })).toHaveAttribute(
    "href",
    "/activity",
  );
  await expectNoSidewaysScroll(page);

  // A's link leads to the revision, where its reservation is cancelled (requirement 5.1).
  await heldByA.click();
  await expect(revisionA.getByText("Reserved", { exact: true })).toBeVisible();
  await revisionA.getByRole("button", { name: "Cancel reservation" }).click();
  await revisionA.getByRole("button", { name: "Cancel it" }).click();
  await expect(revisionA.getByText("Draft", { exact: true })).toBeVisible();

  // Shown again, the dashboard reads both panels afresh: nothing of the resistor is tied up,
  // and with 60 available neither draft is short (requirements 1.4, 5.3).
  const holdingsRead = page.waitForResponse((response) =>
    response.url().includes("/api/projects/holdings"),
  );
  const shortagesRead = page.waitForResponse((response) =>
    response.url().includes("/api/projects/shortages"),
  );
  await nav.getByRole("link", { name: "Dashboard" }).click();
  await Promise.all([holdingsRead, shortagesRead]);
  await expect(tiedUp.getByRole("link", { name: resistor, exact: true })).toHaveCount(0);
  await expect(shortages.getByRole("link", { name: `${project} · B`, exact: true })).toHaveCount(0);
});

/** Defines a lot-counted part in CATEGORY and answers its id, read off the part page's address. */
async function createPart(page: Page, category: string, name: string): Promise<string> {
  await page.goto("/parts");
  await page.getByRole("link", { name: "New part" }).click();
  await page.getByLabel("Category").selectOption({ label: category });
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  const id = new URL(page.url()).pathname.split("/").at(-1);
  if (!id) throw new Error(`no id in the address of ${name}`);
  return id;
}

/** Receives QUANTITY of the part whose page is open into the location named. */
async function receive(page: Page, location: string, quantity: number) {
  const stock = page.getByRole("region", { name: "Stock" });
  await stock.getByRole("button", { name: "Receive" }).click();
  const dialog = page.getByRole("dialog", { name: "Receive stock" });
  // The option reads `name (WX-L-NNNN)` with a code the server minted, so it is found by name.
  const picker = dialog.getByRole("combobox", { name: "Location" });
  const value = await picker
    .getByRole("option", { name: new RegExp(escapeRegExp(location)) })
    .getAttribute("value");
  if (value === null) throw new Error(`no option for the location ${location}`);
  await picker.selectOption(value);
  await dialog.getByRole("spinbutton", { name: "Quantity" }).fill(String(quantity));
  await dialog.getByRole("button", { name: "Receive" }).click();
  await expect(dialog).toBeHidden();
}

/**
 * Picks a part in the focused picker as a person would: types its name, waits for it to be
 * offered, moves to it and takes it with Enter. The box then shows the picked part's name.
 */
async function pickPart(page: Page, picker: Locator, name: string) {
  await page.keyboard.type(name);
  await expect(page.getByRole("option", { name })).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(picker).toHaveAttribute("aria-expanded", "false");
  await expect(picker).toHaveValue(name);
}

/** A line of the BOM's table, found by its part's name. */
function lineRow(lines: Locator, part: string): Locator {
  return lines.getByRole("row").filter({ has: lines.page().getByRole("link", { name: part }) });
}

/** Escapes the stamp so its characters aren't read as a pattern. */
function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
