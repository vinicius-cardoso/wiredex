import { expect, type Locator, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";
import { codeOf } from "./source";

/**
 * Firmware end to end (spec 13): a project's revision A starts a firmware from its Firmware
 * section, and the firmware's page opens running on A. Its first version takes the suggested
 * 0.1.0; one file is typed, another chosen from the computer, and the first edited. Release
 * stays unavailable, saying why, until a changelog is written; then it asks first, and the
 * released version offers no editing. A new version from it takes 0.1.1 and holds its files,
 * and is deleted. Forking A gives a B that runs the firmware; unlinking it there empties B's
 * section, and linking it again from the section's select brings it back, so the firmware runs
 * on A and B. The list finds the firmware by its stamp, and deleting it takes it off the list.
 * On a phone the new firmware form, the firmware's page with its version panel, the revision's
 * page with its Firmware section and the list never scroll sideways: a long line of source
 * scrolls inside its own box.
 *
 * It reuses the session auth.setup.ts saved and never logs out. Every name carries a stamp.
 */

/** A comment wider than any phone, which scrolls inside its box, never the page (11.16). */
const LONG_LINE = `// ${"Reads the BME280 at 0x76 on GPIO21 and GPIO22, then prints it. ".repeat(4).trim()}`;

/** The sketch as typed: a tab, trailing spaces and no final line break, all kept (7.4). */
const SKETCH = [
  '#include "config.h"',
  "",
  LONG_LINE,
  "void setup() {",
  "\tSerial.begin(115200);  ",
  "}",
  "",
  "void loop() {}",
].join("\n");

/** The sketch as edited: the loop waits the interval config.h sets. */
const EDITED = SKETCH.replace("void loop() {}", "void loop() {\n\tdelay(READ_INTERVAL_MS);\n}\n");

/** config.h as the Arduino IDE saves it on Windows, with CRLF; it is stored with LF (7.4). */
const CONFIG = [
  "#pragma once",
  "#define SDA_PIN 21",
  "#define SCL_PIN 22",
  "#define READ_INTERVAL_MS 300000",
  "",
].join("\r\n");

const CHANGELOG = "Reads the BME280 every five minutes.";

test("start a firmware from a revision, release a version, and carry it into a fork", async ({
  page,
}) => {
  test.slow();
  const info = test.info();
  const stamp = `${info.project.name}-${info.workerIndex}-${Date.now()}`;
  const station = `Station ${stamp}`;
  const firmware = `Weather ${stamp}`;

  // A project opens on its revision A, whose Firmware section runs nothing yet.
  await page.goto("/projects");
  await page.getByRole("link", { name: "New project" }).click();
  await page.getByLabel("Name", { exact: true }).fill(station);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: station })).toBeVisible();
  const revisionA = page.getByRole("region", { name: "Revision A", exact: true });
  const sectionA = revisionA.getByRole("region", { name: "Firmware", exact: true });
  await expect(sectionA).toContainText("No firmware runs on this revision yet.");

  // New firmware from the section says which revision it will run on before it is saved, and
  // the firmware's page opens running on A (requirements 3.3, 11.3, 11.4).
  await sectionA.getByRole("link", { name: "New firmware" }).click();
  await expect(page.getByRole("heading", { name: "New firmware" })).toBeVisible();
  await expect(
    page.getByText("It will run on").getByRole("link", { name: `${station} · A` }),
  ).toBeVisible();
  await page.getByLabel("Name", { exact: true }).fill(firmware);
  await page.getByLabel("Board target").fill("esp32:esp32:esp32");
  await page.getByLabel("Framework").selectOption({ label: "Arduino" });
  await expectNoSidewaysScroll(page);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("heading", { name: firmware, level: 1 })).toBeVisible();
  const runsOn = page.getByRole("region", { name: "Runs on" });
  await expect(runsOn.getByRole("link")).toHaveText([`${station} · A`]);

  // The first version takes the suggested 0.1.0 and starts empty, a draft (5.4, 5.5).
  const versions = page.getByRole("navigation", { name: "Versions" });
  await versions.getByRole("button", { name: "New version" }).click();
  const start = page.getByRole("dialog", { name: `New version of ${firmware}` });
  await expect(start.getByLabel("Version number")).toHaveValue("0.1.0");
  await expect(start.getByLabel("Start from")).toHaveValue("");
  await start.getByRole("button", { name: "Start version" }).click();
  await expect(start).toBeHidden();
  const first = page.getByRole("region", { name: "Version 0.1.0", exact: true });
  await expect(first.getByText("Draft", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/versions\/[^/]+$/);
  const { firmwareId, versionId: firstId } = idsOf(page.url());

  // Release is there but unavailable while the draft has no file and no changelog (11.7).
  const release = first.getByRole("button", { name: "Release", exact: true });
  await expect(release).toHaveAttribute("aria-disabled", "true");
  await expect(release).toHaveAccessibleDescription(
    "Add a source file and write a changelog before releasing.",
  );

  // One file typed, kept exactly as typed, its long line scrolling in its box (7.1, 11.9).
  const files = first.getByRole("region", { name: "Source files" });
  await files.getByRole("button", { name: "Add a file" }).click();
  const adding = files.getByRole("form", { name: "New file" });
  await adding.getByLabel("Path", { exact: true }).fill("sketch.ino");
  await adding.getByLabel("Code", { exact: true }).fill(SKETCH);
  await adding.getByRole("button", { name: "Add file", exact: true }).click();
  await expect(adding).toBeHidden();
  const sketch = files.getByRole("region", { name: "sketch.ino", exact: true });
  await expect.poll(() => codeIn(sketch, "sketch.ino")).toBe(SKETCH);
  await expectNoSidewaysScroll(page);

  // Another chosen from the computer, sent at once, its CRLF read back as LF (7.1, 7.4).
  await files.getByLabel("Add files from the computer").setInputFiles({
    name: "config.h",
    mimeType: "text/plain",
    buffer: Buffer.from(CONFIG),
  });
  await expect(files.getByRole("status")).toHaveText("Added 1 file.");
  const config = files.getByRole("region", { name: "config.h", exact: true });
  await expect.poll(() => codeIn(config, "config.h")).toBe(CONFIG.replaceAll("\r\n", "\n"));

  // The typed one edited: renamed and its text replaced (7.8, 11.9). The `.ino` lists first.
  await sketch.getByRole("button", { name: "Edit sketch.ino", exact: true }).click();
  const editing = files.getByRole("form", { name: "Editing sketch.ino" });
  await editing.getByLabel("Path", { exact: true }).fill("weather.ino");
  await editing.getByLabel("Code", { exact: true }).fill(EDITED);
  await expectNoSidewaysScroll(page);
  await editing.getByRole("button", { name: "Save file", exact: true }).click();
  await expect(editing).toBeHidden();
  const weather = files.getByRole("region", { name: "weather.ino", exact: true });
  await expect.poll(() => codeIn(weather, "weather.ino")).toBe(EDITED);
  await expect(sketch).toHaveCount(0);
  await expect(
    files.getByRole("navigation", { name: "Files in this version" }).getByRole("link"),
  ).toHaveText(["weather.ino", "config.h"]);

  // Still no release without a changelog (6.3); with one written, Release asks first (11.7).
  await expect(release).toHaveAccessibleDescription("Write a changelog before releasing.");
  await first.getByRole("button", { name: "Edit version", exact: true }).click();
  const edit = page.getByRole("dialog", { name: "Edit version 0.1.0" });
  await edit.getByLabel("Changelog").fill(CHANGELOG);
  await edit.getByRole("button", { name: "Save", exact: true }).click();
  await expect(edit).toBeHidden();
  await expect(first).toContainText(CHANGELOG);
  await expect(release).not.toHaveAttribute("aria-disabled", "true");
  await release.click();
  const asking = page.getByRole("dialog", { name: "Release version 0.1.0?" });
  await expect(asking).toContainText("Once released, its files and changelog won't change again.");
  await asking.getByRole("button", { name: "Release 0.1.0", exact: true }).click();
  await expect(asking).toBeHidden();

  // Released, it is dated and offers no editing: not its number, changelog or files (6.1, 6.4).
  await expect(first.getByText("Released", { exact: true })).toBeVisible();
  await expect(first.getByText("Released on")).toBeVisible();
  await expect(first.getByRole("button", { name: "Edit version" })).toHaveCount(0);
  await expect(release).toHaveCount(0);
  await expect(files.getByRole("button", { name: "Add a file" })).toHaveCount(0);
  await expect(files.getByLabel("Add files from the computer")).toHaveCount(0);
  await expect(weather.getByRole("button", { name: "Edit weather.ino" })).toHaveCount(0);
  await expect.poll(() => codeIn(weather, "weather.ino")).toBe(EDITED);
  await expectNoSidewaysScroll(page);

  // A new version from it takes 0.1.1 and starts from it, holding its files (5.4, 5.5).
  await first.getByRole("button", { name: "New version from this" }).click();
  const next = page.getByRole("dialog", { name: `New version of ${firmware}` });
  await expect(next.getByLabel("Version number")).toHaveValue("0.1.1");
  await expect(next.getByLabel("Start from")).toHaveValue(firstId);
  await next.getByRole("button", { name: "Start version" }).click();
  await expect(next).toBeHidden();
  const second = page.getByRole("region", { name: "Version 0.1.1", exact: true });
  await expect(second.getByText("Draft", { exact: true })).toBeVisible();
  await expect(second.getByRole("link", { name: "0.1.0", exact: true })).toBeVisible();
  const copied = second.getByRole("region", { name: "Source files" });
  const copiedWeather = copied.getByRole("region", { name: "weather.ino", exact: true });
  await expect.poll(() => codeIn(copiedWeather, "weather.ino")).toBe(EDITED);
  await expect(copied.getByRole("region", { name: "config.h", exact: true })).toBeVisible();

  // Deleted, it goes, and the firmware's page opens its highest version again (8.1).
  await second.getByRole("button", { name: "Delete version" }).click();
  await second.getByRole("button", { name: "Yes, delete it" }).click();
  await expect(page).toHaveURL(new RegExp(`/firmware/${firmwareId}$`));
  await expect(first).toBeVisible();
  await expect(versions.getByRole("link")).toHaveText(["0.1.0 · Released"]);

  // Back on A, which runs the release; forking A gives a B that runs it too (4.1, 11.11).
  await runsOn.getByRole("link", { name: `${station} · A` }).click();
  await expect(sectionA.getByRole("listitem").filter({ hasText: firmware })).toContainText(
    "Latest release 0.1.0",
  );
  await revisionA.getByRole("button", { name: "Fork", exact: true }).click();
  const fork = page.getByRole("dialog", { name: "Fork revision A" });
  await fork.getByRole("button", { name: "Fork", exact: true }).click();
  const revisionB = page.getByRole("region", { name: "Revision B", exact: true });
  const sectionB = revisionB.getByRole("region", { name: "Firmware", exact: true });
  await expect(sectionB.getByRole("link", { name: firmware })).toBeVisible();

  // Unlinked, B runs nothing; linked again from the section's select, it runs it (3.1, 3.2).
  await sectionB.getByRole("button", { name: `Unlink ${firmware}` }).click();
  await expect(sectionB).toContainText("No firmware runs on this revision yet.");
  await sectionB.getByLabel("Firmware to link").selectOption({ label: firmware });
  await sectionB.getByRole("button", { name: "Link", exact: true }).click();
  await expect(sectionB.getByRole("link", { name: firmware })).toBeVisible();
  await expect(sectionB).not.toContainText("No firmware runs on this revision yet.");
  // The revision's page, its Firmware section and all, fits the phone (11.16).
  await expectNoSidewaysScroll(page);

  // So the firmware runs on A and B, in the order they were linked (requirement 3.5).
  await sectionB.getByRole("link", { name: firmware }).click();
  await expect(page.getByRole("heading", { name: firmware, level: 1 })).toBeVisible();
  await expect(runsOn.getByRole("link")).toHaveText([`${station} · A`, `${station} · B`]);

  // The list finds it by its stamp, the search kept in the address (11.2).
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Firmware", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Firmware", exact: true, level: 1 }),
  ).toBeVisible();
  const search = page.getByRole("searchbox", { name: "Search firmware by name or board" });
  await search.fill(stamp);
  await expect(page).toHaveURL(new RegExp(`[?&]q=${stamp}$`));
  const rows = page.getByRole("table", { name: "Firmware" }).getByRole("row");
  await expect(rows).toHaveCount(2);
  const row = rows.filter({ hasText: firmware });
  await expect(row).toContainText("0.1.0");
  await expect(row).toContainText("1 version");
  await expectNoSidewaysScroll(page);

  // Deleted, with its version and links, it is off the list (1.9).
  await row.getByRole("link", { name: firmware }).click();
  await page.getByRole("button", { name: "Delete firmware" }).click();
  await page.getByRole("button", { name: "Yes, delete it" }).click();
  await expect(page).toHaveURL(/\/firmware$/);
  await search.fill(stamp);
  await expect(page.getByText("No firmware matches this search.")).toBeVisible();
});

/** The code in FILE's box, the box named by its PATH as a screen reader finds it (14, 2.4). */
function codeIn(file: Locator, path: string): Promise<string> {
  return codeOf(file.getByRole("group", { name: path, exact: true }));
}

/** The firmware's id and the open version's, read off a version's address. */
function idsOf(address: string): { firmwareId: string; versionId: string } {
  const match = new URL(address).pathname.match(/^\/firmware\/([^/]+)\/versions\/([^/]+)$/);
  const [, firmwareId, versionId] = match ?? [];
  if (!firmwareId || !versionId) throw new Error(`no version in the address ${address}`);
  return { firmwareId, versionId };
}
