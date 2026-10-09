import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, type Locator, type Page, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";

/**
 * A version's builds end to end (spec 20): a draft offers none; released, its panel shows the
 * command that makes one. A build's zip added from the computer is listed as the newest, and
 * *Flash from the browser* offers its binaries at the offsets its manifest gives, with no file
 * to choose. Removed, the version has none again. The zip is the one the API's own `bundle()`
 * wrote for the web's tests, so the three sides agree on the format.
 *
 * No board is written: a journey has no serial port. It reuses the session auth.setup.ts saved
 * and never logs out. Every name carries a stamp.
 */

const BUILD = fileURLToPath(
  new URL("../../apps/web/src/features/firmware/flashing/fixtures/build.zip", import.meta.url),
);
const SKETCH = "void setup() {}\n\nvoid loop() {}\n";

test("store a build on a released version and have the flash dialog offer it", async ({ page }) => {
  const info = test.info();
  const firmware = `Blink ${info.project.name}-${info.workerIndex}-${Date.now()}`;

  await page.goto("/firmware/new");
  await page.getByLabel("Name", { exact: true }).fill(firmware);
  await page.getByLabel("Board target").fill("esp32:esp32:esp32");
  await page.getByLabel("Framework").selectOption({ label: "Arduino" });
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("heading", { name: firmware, level: 1 })).toBeVisible();
  await page
    .getByRole("navigation", { name: "Versions" })
    .getByRole("button", { name: "New version" })
    .click();
  const panel = await startVersion(page, firmware, "1.0.0");
  const files = panel.getByRole("region", { name: "Source files" });
  await files
    .getByLabel("Add files from the computer")
    .setInputFiles({ name: "blink.ino", mimeType: "text/plain", buffer: Buffer.from(SKETCH) });
  await expect(files.getByRole("status").filter({ hasText: "Added" })).toHaveText("Added 1 file.");

  // A draft's source can still change, so it holds no build (requirement 4.2).
  const builds = panel.getByRole("region", { name: "Builds", exact: true });
  await expect(builds).toBeHidden();
  await release(page, panel, "1.0.0", "Blinks.");

  // Released, with none yet: the command that makes one, the name quoted for the shell (4.1).
  await expect(builds).toContainText("No build is stored for this version yet.");
  await expect(builds.getByText(`wiredex firmware build "${firmware}" 1.0.0`)).toBeVisible();

  await builds.getByLabel("Add a build's zip").setInputFiles({
    name: "build.zip",
    mimeType: "application/zip",
    buffer: readFileSync(BUILD),
  });
  await expect(builds.getByRole("status")).toHaveText("The build is stored.");
  const stored = builds.getByRole("listitem");
  await expect(stored).toHaveCount(1);
  await expect(stored).toContainText("build");
  await expect(stored).toContainText("Newest");
  await expect(stored.getByRole("link", { name: /^Download / })).toHaveAttribute(
    "href",
    /\/api\/files\/attachments\/[^/]+\/content$/,
  );
  await expectNoSidewaysScroll(page);

  // The dialog offers the stored build in place of the file picker (3.1), where the browser
  // has Web Serial at all; where it hasn't, it says so before anything else.
  await panel.getByRole("button", { name: "Flash from the browser" }).click();
  const dialog = page.getByRole("dialog", { name: `Flash ${firmware} 1.0.0 from the browser` });
  if (await page.evaluate(() => "serial" in navigator)) {
    const binaries = dialog.getByRole("list", { name: "Binaries" }).getByRole("listitem");
    await expect(binaries).toHaveCount(4);
    await expect(binaries.nth(2)).toContainText("boot_app0.bin");
    await expect(binaries.nth(2)).toContainText("at 0xe000");
    await expect(binaries.nth(3)).toContainText("at 0x10000");
    await expect(dialog.locator('input[type="file"]')).toHaveCount(0);
    await expectNoSidewaysScroll(page);
  } else {
    await expect(dialog).toContainText("This browser can't reach a serial port.");
  }
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();

  // Removed as any attachment is, after a question (1.5).
  await stored.getByRole("button", { name: /^Remove / }).click();
  await builds.getByRole("button", { name: "Remove attachment" }).click();
  await expect(builds).toContainText("No build is stored for this version yet.");
});

async function startVersion(page: Page, firmware: string, number: string): Promise<Locator> {
  const dialog = page.getByRole("dialog", { name: `New version of ${firmware}` });
  await dialog.getByLabel("Version number").fill(number);
  await dialog.getByRole("button", { name: "Start version" }).click();
  await expect(dialog).toBeHidden();
  const panel = page.getByRole("region", { name: `Version ${number}`, exact: true });
  await expect(panel.getByText("Draft", { exact: true })).toBeVisible();
  return panel;
}

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
