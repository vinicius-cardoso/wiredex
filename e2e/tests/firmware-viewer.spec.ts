import { expect, type Locator, type Page, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";
import { codeOf } from "./source";

/**
 * The firmware viewer end to end (spec 14): a firmware's 1.0.0 holds app.ino and util.h and is
 * released; its 1.1.0 starts from it, changes a line of app.ino and adds two after it, removes
 * util.h and adds util.cpp. On 1.0.0, app.ino reads as C++, its keywords highlighted; *Copy*
 * puts exactly its text on the clipboard; and *Wrap long lines* leaves its box nothing to scroll
 * sideways. *Compare with 1.0.0* on 1.1.0 counts one file changed, one added and one removed, and
 * shows app.ino's hunk with its removed and added lines. Swapping the selects reverses the
 * comparison, each choice a new address that Back walks. On a phone neither the version's page
 * nor the comparison scrolls sideways: long lines scroll inside their own box.
 *
 * The versions are set up through the pages, as firmware.spec.ts sets them up, since no helper
 * here writes through the API. It reuses the session auth.setup.ts saved and never logs out.
 * Every name carries a stamp.
 */

// *Copy* writes the clipboard, and the journey reads it back (requirement 3.1).
test.use({ permissions: ["clipboard-read", "clipboard-write"] });

/** A comment wider than any screen: it scrolls inside its box unless lines wrap (2.2, 7.3). */
const LONG_LINE = `  // ${"Blinks the LED on pin 13, then waits as long again before the next blink. ".repeat(4).trim()}`;

/** 1.0.0's sketch, ending in a line break as the Arduino IDE saves it. */
const APP = [
  "const int LED = 13;",
  "",
  "void setup() {",
  "  pinMode(LED, OUTPUT);",
  "}",
  "",
  "void loop() {",
  LONG_LINE,
  "  blink(LED, 500);",
  "}",
  "",
].join("\n");

/** 1.1.0's: line 9 blinks faster, and two lines follow it. */
const NEXT = APP.replace(
  "  blink(LED, 500);\n",
  "  blink(LED, 250);\n  delay(250);\n  blink(LED, 1000);\n",
);

/** 1.0.0's header, three lines; 1.1.0 removes it. */
const UTIL_H = ["#pragma once", "", "void blink(int pin, int ms);", ""].join("\n");

/** 1.1.0's source, eight lines, added. */
const UTIL_CPP = [
  "#include <Arduino.h>",
  "",
  "void blink(int pin, int ms) {",
  "  digitalWrite(pin, HIGH);",
  "  delay(ms);",
  "  digitalWrite(pin, LOW);",
  "  delay(ms);",
  "}",
  "",
].join("\n");

test("read, copy and compare the source of two firmware versions", async ({ page }) => {
  test.slow();
  const info = test.info();
  const stamp = `${info.project.name}-${info.workerIndex}-${Date.now()}`;
  const firmware = `Blinker ${stamp}`;

  // A firmware running on no revision, its 1.0.0 holding app.ino and util.h, released.
  await page.goto("/firmware/new");
  await page.getByLabel("Name", { exact: true }).fill(firmware);
  await page.getByLabel("Board target").fill("arduino:avr:uno");
  await page.getByLabel("Framework").selectOption({ label: "Arduino" });
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("heading", { name: firmware, level: 1 })).toBeVisible();
  await page
    .getByRole("navigation", { name: "Versions" })
    .getByRole("button", { name: "New version" })
    .click();
  const first = await startVersion(page, firmware, "1.0.0");
  const { firmwareId, versionId: firstId } = idsOf(page.url());
  const files = first.getByRole("region", { name: "Source files" });
  await files
    .getByLabel("Add files from the computer")
    .setInputFiles([textFile("app.ino", APP), textFile("util.h", UTIL_H)]);
  await expect(files.getByRole("status").filter({ hasText: "Added" })).toHaveText("Added 2 files.");
  await release(page, first, "1.0.0");

  // On the release, app.ino reads as C++: its keywords highlighted, its code exactly the text
  // stored, the line numbers beside it left out (requirements 1.1, 1.2, 2.1).
  // The release lists its files, and shows one's text once it is picked.
  await expect(files.getByRole("group")).toHaveCount(0);
  await openFile(files, "app.ino");
  const app = files.getByRole("region", { name: "app.ino", exact: true });
  const appBox = app.getByRole("group", { name: "app.ino", exact: true });
  await expect(appBox.locator(".tok-keyword").filter({ hasText: /^const$/ })).toBeVisible();
  await expect.poll(() => codeOf(appBox)).toBe(APP);

  // Copy puts exactly the stored text on the clipboard, no numbers and no wrapping in it, and
  // says which file it copied (3.1, 3.2, 3.4).
  await app.getByRole("button", { name: "Copy app.ino", exact: true }).click();
  await expect(app.getByRole("status")).toHaveText("Copied app.ino.");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(APP);

  // Off, the long comment scrolls inside its box, never the page; on, it breaks at the box's
  // width and there is nothing left to scroll sideways (2.2, 7.3).
  const wrap = files.getByRole("switch", { name: "Wrap long lines" });
  await expect(wrap).not.toBeChecked();
  expect(await scrollsSideways(appBox)).toBe(true);
  await expectNoSidewaysScroll(page);
  await wrap.check();
  await expect(wrap).toBeChecked();
  await expect.poll(() => scrollsSideways(appBox)).toBe(false);
  await expectNoSidewaysScroll(page);

  // 1.1.0 starts from it: app.ino's line 9 changed and two lines added after it, util.h removed
  // and util.cpp added.
  await first.getByRole("button", { name: "New version from this" }).click();
  const second = await startVersion(page, firmware, "1.1.0");
  const { versionId: secondId } = idsOf(page.url());
  const nextFiles = second.getByRole("region", { name: "Source files" });
  await openFile(nextFiles, "app.ino");
  await nextFiles.getByRole("button", { name: "Edit app.ino", exact: true }).click();
  const editing = nextFiles.getByRole("form", { name: "Editing app.ino" });
  await editing.getByLabel("Code", { exact: true }).fill(NEXT);
  await editing.getByRole("button", { name: "Save file", exact: true }).click();
  await expect(editing).toBeHidden();
  await openFile(nextFiles, "util.h");
  await nextFiles.getByRole("button", { name: "Remove util.h", exact: true }).click();
  await nextFiles.getByRole("button", { name: "Yes, remove it" }).click();
  await expect(nextFiles.getByRole("region", { name: "util.h", exact: true })).toHaveCount(0);
  await nextFiles
    .getByLabel("Add files from the computer")
    .setInputFiles(textFile("util.cpp", UTIL_CPP));
  await expect(
    nextFiles.getByRole("navigation", { name: "Files in this version" }).getByRole("link"),
  ).toContainText(["app.ino", "util.cpp"]);
  await openFile(nextFiles, "app.ino");
  // A draft's files offer Copy as a release's do (3.4).
  await expect(nextFiles.getByRole("button", { name: "Copy app.ino", exact: true })).toBeVisible();

  // Compare with 1.0.0 opens the base against it, both kept in the address, and the selects
  // offer every version of the firmware, the draft included (4.6, 4.7).
  await second.getByRole("link", { name: "Compare with 1.0.0", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Compare versions", level: 1 })).toBeVisible();
  await expect(page).toHaveURL(comparing(firmwareId, firstId, secondId));
  const from = page.getByRole("combobox", { name: "From", exact: true });
  const to = page.getByRole("combobox", { name: "To", exact: true });
  await expect(from.locator("option")).toHaveText(["1.1.0 · Draft", "1.0.0 · Released"]);
  await expect(from.locator("option:checked")).toHaveText("1.0.0 · Released");
  await expect(to.locator("option:checked")).toHaveText("1.1.0 · Draft");

  // One file of each kind: app.ino's three lines and util.cpp's eight added, app.ino's one and
  // util.h's three removed (4.1, 4.3, 4.4).
  const summary = page.getByRole("list", { name: "Summary" }).getByRole("listitem");
  await expect(summary).toHaveText([
    "1 file changed",
    "1 file added",
    "1 file removed",
    "11 lines added",
    "4 lines removed",
  ]);
  await expect(page.getByRole("region", { name: "util.cpp, added", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "util.h, removed", exact: true })).toBeVisible();

  // app.ino's hunk: its three lines of context above, the long comment among them, then line 9
  // removed and lines 9 to 11 added, each numbered in its own version and marked with − or + and
  // the word a screen reader reads (4.2, 5.1, 5.3).
  const changed = page.getByRole("region", { name: "app.ino, changed", exact: true });
  const table = changed.getByRole("table", { name: "Lines changed in app.ino" });
  await expect(table.getByText("Lines 6–10 → 6–12", { exact: true })).toBeVisible();
  await expect(marked(table, "removed").getByRole("cell")).toHaveText([
    "9",
    "",
    "−removed",
    "blink(LED, 500);",
  ]);
  await expect(marked(table, "added").getByRole("cell")).toHaveText([
    ...["", "9", "+added", "blink(LED, 250);"],
    ...["", "10", "+added", "delay(250);"],
    ...["", "11", "+added", "blink(LED, 1000);"],
  ]);
  // The long comment scrolls inside the table's box, never the phone's page (7.3).
  await expectNoSidewaysScroll(page);

  // Swapped, the selects reverse it: util.h comes back and util.cpp goes. On the way, the same
  // version on both sides asks for two (4.8); each choice is a new address (4.7).
  await from.selectOption({ label: "1.1.0 · Draft" });
  const same = page.getByText("Choose two different versions to compare.");
  await expect(same).toBeVisible();
  await to.selectOption({ label: "1.0.0 · Released" });
  await expect(page).toHaveURL(comparing(firmwareId, secondId, firstId));
  await expect(summary).toHaveText([
    "1 file changed",
    "1 file added",
    "1 file removed",
    "4 lines added",
    "11 lines removed",
  ]);
  await expect(page.getByRole("region", { name: "util.h, added", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "util.cpp, removed", exact: true })).toBeVisible();
  await expect(table.getByText("Lines 6–12 → 6–10", { exact: true })).toBeVisible();
  await expect(marked(table, "removed").getByRole("cell")).toHaveText([
    ...["9", "", "−removed", "blink(LED, 250);"],
    ...["10", "", "−removed", "delay(250);"],
    ...["11", "", "−removed", "blink(LED, 1000);"],
  ]);
  await expect(marked(table, "added").getByRole("cell")).toHaveText([
    "",
    "9",
    "+added",
    "blink(LED, 500);",
  ]);

  // Back walks the choices: the same version twice, then the comparison first opened (4.7).
  await page.goBack();
  await expect(same).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(comparing(firmwareId, firstId, secondId));
  await expect(page.getByRole("region", { name: "util.cpp, added", exact: true })).toBeVisible();
});

/**
 * Starts the version NUMBER from the *New version* dialog that is open, and answers its panel
 * once the page has moved to the new version's address, where `idsOf` reads its id.
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

/** Writes the draft PANEL's changelog, then releases it, answering Release's question. */
async function release(page: Page, panel: Locator, number: string) {
  await panel.getByRole("button", { name: "Edit version", exact: true }).click();
  const edit = page.getByRole("dialog", { name: `Edit version ${number}` });
  await edit.getByLabel("Changelog").fill("Blinks the LED on pin 13.");
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

/** Whether BOX holds lines wider than itself, to scroll sideways. */
function scrollsSideways(box: Locator): Promise<boolean> {
  return box.evaluate((element) => element.scrollWidth > element.clientWidth);
}

/** TABLE's rows whose change cell says KIND, the word a screen reader reads beside − or +. */
function marked(table: Locator, kind: "added" | "removed"): Locator {
  return table.getByRole("row").filter({
    has: table.page().getByRole("cell", { name: kind, exact: true }),
  });
}

/** The comparison's address, the versions FROM and TO in its query (requirement 4.7). */
function comparing(firmwareId: string, from: string, to: string): RegExp {
  return new RegExp(`/firmware/${firmwareId}/compare\\?from=${from}&to=${to}$`);
}

/** The firmware's id and the open version's, read off a version's address. */
function idsOf(address: string): { firmwareId: string; versionId: string } {
  const match = new URL(address).pathname.match(/^\/firmware\/([^/]+)\/versions\/([^/]+)$/);
  const [, firmwareId, versionId] = match ?? [];
  if (!firmwareId || !versionId) throw new Error(`no version in the address ${address}`);
  return { firmwareId, versionId };
}

/** Opens the file at PATH from the version's list of files, as a reader does to read it. */
async function openFile(files: Locator, path: string): Promise<void> {
  const index = files.getByRole("navigation", { name: "Files in this version" });
  await index.getByRole("link", { name: path }).click();
}
