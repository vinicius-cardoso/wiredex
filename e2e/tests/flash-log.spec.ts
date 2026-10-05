import { expect, type Locator, type Page, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";

/**
 * The flash log end to end (spec 15): a category tracked individually, a board part and one
 * unit received, whose page says no flash is logged yet; a firmware with 1.0.0 and 1.1.0
 * released. *Log a flash* on 1.0.0's panel picks the unit by its code, and the firmware's boards
 * list it on 1.0.0 with 1.1.0 out, as its own page then does. *Log a flash* on the unit's page
 * logs 1.1.0, now current with nothing newer, the log listing both. Deleting 1.1.0 is refused,
 * listing the unit's flash; removing that entry from the refusal makes 1.0.0 current again.
 * Retired, the unit leaves the firmware's boards, and its page keeps the log without *Log a
 * flash*. On a phone the unit's page, the dialog from either end, the refusal and the boards
 * never scroll sideways: the log reflows into cards, the other tables scroll in their own box.
 * On a laptop the log has a row of its own, where every *Remove* shows.
 *
 * The data is set up through the pages, as units.spec.ts and firmware-viewer.spec.ts set it up,
 * since no helper here writes through the API. It reuses the session auth.setup.ts saved and
 * never logs out. Every name carries a stamp.
 */

/** The sketch both versions hold: 1.1.0 starts from 1.0.0 and only its changelog differs. */
const SKETCH = [
  "void setup() {",
  "  pinMode(LED_BUILTIN, OUTPUT);",
  "}",
  "",
  "void loop() {",
  "  digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));",
  "  delay(500);",
  "}",
  "",
].join("\n");

test("log flashes on a board from both ends and read what it runs", async ({ page }) => {
  test.slow();
  const info = test.info();
  const stamp = `${info.project.name}-${info.workerIndex}-${Date.now()}`;
  const drawer = `Drawer ${stamp}`;
  const category = `Boards ${stamp}`;
  const part = `Pico ${stamp}`;
  const firmware = `Blink ${stamp}`;

  // A drawer to receive into, and a category tracked individually, so its part comes in as a
  // unit with a page of its own (06; requirement 8.1's page).
  await page.goto("/locations");
  await page.getByLabel("Add a location").fill(drawer);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name: drawer })).toBeVisible();
  await page.goto("/categories");
  await page.getByLabel("Add a category").fill(category);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByRole("treeitem", { name: category }).click();
  const tracking = page
    .getByRole("region", { name: `The category ${category}` })
    .getByLabel("Tracked individually");
  await tracking.selectOption("yes");
  // The select follows the stored flag, so this waits until the change is saved.
  await expect(tracking).toHaveValue("yes");

  // A board part, and one unit of it received; the dialog shows the code it minted.
  await page.goto("/parts");
  await page.getByRole("link", { name: "New part" }).click();
  await page.getByLabel("Category").selectOption({ label: category });
  await page.getByLabel("Name", { exact: true }).fill(part);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: part })).toBeVisible();
  await page
    .getByRole("region", { name: "Stock" })
    .getByRole("button", { name: "Receive units" })
    .click();
  const receive = page.getByRole("dialog", { name: "Receive units" });
  await selectLocation(receive.getByLabel("Location"), drawer);
  await receive.getByLabel("Quantity").press("Enter");
  await expect(receive.getByText(/Received:/)).toBeVisible();
  const code = ((await receive.getByRole("listitem").textContent()) ?? "").trim();
  expect(code).toMatch(/^WX-U-\d{4,}$/);
  await receive.getByRole("button", { name: "Cancel" }).click();

  // Its page has a Firmware section that says nothing is logged yet (requirement 8.1).
  await page.getByRole("region", { name: "Units" }).getByRole("link", { name: code }).click();
  await expect(page.getByRole("heading", { name: code, level: 1 })).toBeVisible();
  const unitPage = page.url();
  const section = page.getByRole("region", { name: "Firmware", exact: true });
  await expect(section).toContainText("No flash is logged on this board yet.");
  // The section's facts: the current firmware, its version with any newer release, and when.
  const running = section.getByRole("definition");

  // A firmware whose 1.0.0 holds the sketch and is released, and a 1.1.0 started from it, also
  // released, so 1.1.0 is the newer release of a board on 1.0.0.
  await page.goto("/firmware/new");
  await page.getByLabel("Name", { exact: true }).fill(firmware);
  await page.getByLabel("Board target").fill("rp2040:rp2040:rpipico");
  await page.getByLabel("Framework").selectOption({ label: "Arduino" });
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("heading", { name: firmware, level: 1 })).toBeVisible();
  const versions = page.getByRole("navigation", { name: "Versions" });
  await versions.getByRole("button", { name: "New version" }).click();
  const first = await startVersion(page, firmware, "1.0.0");
  const files = first.getByRole("region", { name: "Source files" });
  await files
    .getByLabel("Add files from the computer")
    .setInputFiles(textFile("blink.ino", SKETCH));
  await expect(files.getByRole("status").filter({ hasText: "Added" })).toHaveText("Added 1 file.");
  await release(page, first, "1.0.0", "Blinks the built-in LED.");
  await first.getByRole("button", { name: "New version from this" }).click();
  const second = await startVersion(page, firmware, "1.1.0");
  await release(page, second, "1.1.0", "Says what it does in its changelog.");
  const boards = page.getByRole("region", { name: "Boards", exact: true });
  await expect(boards).toContainText("No board runs this firmware yet.");

  // *Log a flash* on 1.0.0's panel picks the board by its code, the time left as now
  // (requirements 1.1, 1.2, 8.3).
  await versions.getByRole("link", { name: "1.0.0 · Released" }).click();
  await first.getByRole("button", { name: "Log a flash" }).click();
  const fromVersion = page.getByRole("dialog", { name: `Log a flash of ${firmware} 1.0.0` });
  const pick = fromVersion.getByRole("combobox", { name: "Board" });
  await pick.fill(code);
  // The search matches codes holding this one too, so pick the option that is exactly it.
  await fromVersion.getByRole("option", { name: new RegExp(`^${escapeRegExp(code)} `) }).click();
  await expect(pick).toHaveValue(code);
  await fromVersion.getByLabel("Notes", { exact: true }).fill("Checking a new board");
  await expectNoSidewaysScroll(page);
  await fromVersion.getByRole("button", { name: "Log flash", exact: true }).click();
  await expect(fromVersion).toBeHidden();

  // The firmware's boards list it in place, on 1.0.0 with 1.1.0 out in words, and link to its
  // page (requirements 4.1, 8.6, 8.8).
  const board = boards.getByRole("row").filter({
    has: page.getByRole("link", { name: code, exact: true }),
  });
  await expect(board.getByRole("link", { name: "1.0.0", exact: true })).toBeVisible();
  await expect(board.getByRole("link", { name: "1.1.0 is out", exact: true })).toBeVisible();
  await expect(board).toContainText("Not in a build");
  await expectNoSidewaysScroll(page);
  await board.getByRole("link", { name: code, exact: true }).click();
  await expect(page).toHaveURL(unitPage);

  // Its page shows the firmware and 1.0.0 current, with 1.1.0 out (requirements 2.2, 2.3, 8.1).
  await expect(running.getByRole("link", { name: firmware, exact: true })).toBeVisible();
  await expect(running.getByRole("link", { name: "1.0.0", exact: true })).toBeVisible();
  await expect(running.getByRole("link", { name: "1.1.0 is out", exact: true })).toBeVisible();
  // The log stays within the page, its hidden header included (requirement 8.11).
  await expectNoSidewaysScroll(page);

  // *Log a flash* there offers the workspace's firmware and only its released versions, highest
  // first, the time defaulting to now (requirement 8.2); it logs 1.1.0.
  await section.getByRole("button", { name: "Log a flash" }).click();
  const fromUnit = page.getByRole("dialog", { name: `Log a flash on ${code}` });
  await fromUnit.getByLabel("Firmware", { exact: true }).selectOption({ label: firmware });
  const version = fromUnit.getByLabel("Version", { exact: true });
  await expect(version.locator("option")).toHaveText(["1.1.0", "1.0.0"]);
  await version.selectOption({ label: "1.1.0" });
  await expect(fromUnit.getByLabel("Flashed at")).toHaveValue(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/);
  await fromUnit.getByLabel("Notes", { exact: true }).fill("Blinking faster");
  await expectNoSidewaysScroll(page);
  await fromUnit.getByRole("button", { name: "Log flash", exact: true }).click();
  await expect(fromUnit).toBeHidden();

  // 1.1.0 is current, nothing newer, and the log lists both, newest first (2.1, 2.2, 8.8).
  await expect(running.getByRole("link", { name: "1.1.0", exact: true })).toBeVisible();
  await expect(running.getByText(/ is out$/)).toHaveCount(0);
  const log = page
    .getByRole("region", { name: "Flash log" })
    .getByRole("table", { name: `Flash log of ${code}, newest first` });
  await expect(log.getByRole("link", { name: /^1\.\d\.0$/ })).toHaveText(["1.1.0", "1.0.0"]);
  await expect(log.getByRole("row").filter({ hasText: "Blinking faster" })).toContainText("1.1.0");
  await expect(log.getByRole("row").filter({ hasText: "Checking a new board" })).toContainText(
    "1.0.0",
  );
  await expectNoSidewaysScroll(page);
  // On a laptop, identity and firmware share the first row and the log takes the whole next
  // one, so every column and every *Remove* fit with no scrollbar of its own.
  if (info.project.name === "desktop") {
    for (const size of LAPTOPS) {
      await page.setViewportSize(size);
      await expect(() => expectBoardLayout(page, log, section)).toPass();
    }
    await page.setViewportSize({ width: 1280, height: 720 });
  }

  // The firmware's page lists the board on 1.1.0, with no newer release (requirement 4.1).
  await running.getByRole("link", { name: firmware, exact: true }).click();
  await expect(page.getByRole("heading", { name: firmware, level: 1 })).toBeVisible();
  await expect(board.getByRole("link", { name: "1.1.0", exact: true })).toBeVisible();
  await expect(board.getByText(/ is out$/)).toHaveCount(0);
  await expectNoSidewaysScroll(page);

  // Deleting 1.1.0, the version the page opens, is refused, listing the board's flash with its
  // code linking to its page (requirements 5.1, 8.7).
  await second.getByRole("button", { name: "Delete version" }).click();
  await second.getByRole("button", { name: "Yes, delete it" }).click();
  await expect(second.getByRole("alert")).toHaveText(
    "1.1.0 is in a board's flash log: remove those entries to delete it.",
  );
  const inTheWay = second.getByRole("list", { name: "Flash log entries in the way" });
  await expect(inTheWay.getByRole("listitem")).toHaveCount(1);
  await expect(inTheWay.getByRole("link", { name: code, exact: true })).toBeVisible();
  await expectNoSidewaysScroll(page);

  // Removed from there, after asking in its row, the entry goes, and the board is back on 1.0.0
  // with 1.1.0 out, in place (requirements 3.1, 3.2, 8.5, 8.8).
  await inTheWay
    .getByRole("button", {
      name: new RegExp(`^Remove the flash of 1\\.1\\.0 on ${escapeRegExp(code)} `),
    })
    .click();
  await inTheWay.getByRole("button", { name: "Yes, remove it" }).click();
  await expect(
    second.getByText("Those entries are removed: delete it again to finish."),
  ).toBeVisible();
  await expect(inTheWay).toHaveCount(0);
  await expect(board.getByRole("link", { name: "1.0.0", exact: true })).toBeVisible();
  await expect(board.getByRole("link", { name: "1.1.0 is out", exact: true })).toBeVisible();

  // The unit's page agrees: 1.0.0 current again, 1.1.0 out, one entry left (requirement 3.2).
  await board.getByRole("link", { name: code, exact: true }).click();
  await expect(page).toHaveURL(unitPage);
  await expect(running.getByRole("link", { name: "1.0.0", exact: true })).toBeVisible();
  await expect(running.getByRole("link", { name: "1.1.0 is out", exact: true })).toBeVisible();
  await expect(log.getByRole("link", { name: /^1\.\d\.0$/ })).toHaveText(["1.0.0"]);

  // Retired, it keeps its log but offers no *Log a flash*, saying why (requirements 2.4, 8.4).
  await page.getByRole("button", { name: "Retire", exact: true }).click();
  const retire = page.getByRole("dialog", { name: `Retire ${code}` });
  await retire.getByRole("button", { name: "Retire", exact: true }).click();
  await expect(retire).toBeHidden();
  await expect(page.getByText("Retired", { exact: true })).toBeVisible();
  await expect(section).toContainText(
    "This unit is retired, so no flash can be logged on it. Un-retire it first.",
  );
  await expect(section.getByRole("button", { name: "Log a flash" })).toHaveCount(0);
  await expect(running.getByRole("link", { name: "1.0.0", exact: true })).toBeVisible();
  await expect(log.getByRole("link", { name: /^1\.\d\.0$/ })).toHaveText(["1.0.0"]);
  await expectNoSidewaysScroll(page);

  // And it is off the firmware's boards (requirement 4.2).
  await running.getByRole("link", { name: firmware, exact: true }).click();
  await expect(page.getByRole("heading", { name: firmware, level: 1 })).toBeVisible();
  await expect(boards).toContainText("No board runs this firmware yet.");
  await expect(board).toHaveCount(0);
});

/** The laptop screens the redesign is checked at. */
const LAPTOPS = [
  { width: 1366, height: 768 },
  { width: 1440, height: 810 },
  { width: 1920, height: 930 },
];

/**
 * The board page's blocks at a laptop size: Identity and FIRMWARE side by side, the log's
 * frame (the table's parent) not scrolling, and each of LOG's *Remove* buttons inside the frame
 * and the screen.
 */
async function expectBoardLayout(page: Page, log: Locator, firmware: Locator) {
  const identity = await box(page.getByRole("region", { name: "Identity" }));
  const current = await box(firmware);
  expect(Math.abs(identity.y - current.y)).toBeLessThanOrEqual(1);
  expect(current.x).toBeGreaterThan(identity.x + identity.width - 1);

  const frame = log.locator("xpath=..");
  const { scrollWidth, clientWidth } = await frame.evaluate((element) => ({
    scrollWidth: element.scrollWidth,
    clientWidth: element.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
  const inFrame = await box(frame);
  const screen = page.viewportSize()?.width ?? 0;
  const removes = await log.getByRole("button", { name: /^Remove the flash of / }).all();
  expect(removes.length).toBeGreaterThan(0);
  for (const remove of removes) {
    const button = await box(remove);
    expect(button.x).toBeGreaterThanOrEqual(inFrame.x - 1);
    expect(button.x + button.width).toBeLessThanOrEqual(inFrame.x + inFrame.width + 1);
    expect(button.x + button.width).toBeLessThanOrEqual(screen);
  }
}

/** LOCATOR's box on the page; it must be rendered. */
async function box(locator: Locator) {
  const rect = await locator.boundingBox();
  if (rect === null) throw new Error("the element isn't rendered");
  return rect;
}

/**
 * Starts the version NUMBER from the *New version* dialog that is open, and answers its panel
 * once the page has moved to the new version's address. As firmware-viewer.spec.ts has it.
 */
async function startVersion(page: Page, firmware: string, number: string): Promise<Locator> {
  const before = page.url();
  const dialog = page.getByRole("dialog", { name: `New version of ${firmware}` });
  await dialog.getByLabel("Version number").fill(number);
  await dialog.getByRole("button", { name: "Start version" }).click();
  await expect(dialog).toBeHidden();
  const panel = page.getByRole("region", { name: `Version ${number}`, exact: true });
  await expect(panel.getByText("Draft", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(
    (url) => url.href !== before && /\/versions\/[^/]+$/.test(url.pathname),
  );
  return panel;
}

/** Writes the draft PANEL's CHANGELOG, then releases it, answering Release's question. */
async function release(page: Page, panel: Locator, number: string, changelog: string) {
  await panel.getByRole("button", { name: "Edit version", exact: true }).click();
  const edit = page.getByRole("dialog", { name: `Edit version ${number}` });
  await edit.getByLabel("Changelog").fill(changelog);
  await edit.getByRole("button", { name: "Save", exact: true }).click();
  await expect(edit).toBeHidden();
  const button = panel.getByRole("button", { name: "Release", exact: true });
  await expect(button).not.toHaveAttribute("aria-disabled", "true");
  await button.click();
  const asking = page.getByRole("dialog", { name: `Release version ${number}?` });
  await asking.getByRole("button", { name: `Release ${number}`, exact: true }).click();
  await expect(asking).toBeHidden();
  await expect(panel.getByText("Released", { exact: true })).toBeVisible();
}

/** A text file as the computer's file chooser hands it over. */
function textFile(name: string, text: string) {
  return { name, mimeType: "text/plain", buffer: Buffer.from(text) };
}

/**
 * Picks a location in a unit dialog by the name it was given, as units.spec.ts does: the
 * option reads `name (WX-L-NNNN)`, the code minted by the server.
 */
async function selectLocation(combobox: Locator, name: string) {
  const value = await combobox
    .getByRole("option", { name: new RegExp(escapeRegExp(name)) })
    .getAttribute("value");
  if (value === null) throw new Error(`no option for the location ${name}`);
  await combobox.selectOption(value);
}

/** Escapes TEXT so its characters aren't read as a pattern. */
function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
