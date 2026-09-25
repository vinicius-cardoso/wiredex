import { expect, test } from "@playwright/test";

/**
 * A pinout, end to end: a part filed with no pins, a datasheet's table pasted into the
 * editor, saved, read back, and then narrowed by an alternate function.
 *
 * It reuses the session auth.setup.ts saved, like every other journey. The local database
 * keeps what a run creates, so the names carry a stamp.
 */

/**
 * Three pins of a BME280 as a spreadsheet copies them: tab-separated, under a header line,
 * with the datasheet's own spellings (`PWR`, `I/O`), two functions in one cell, a row that
 * stops early, and levels written the `3V3` way.
 */
const PASTED = [
  "Pin\tName\tType\tFunctions\tVoltage",
  "1\tVDD\tPWR\t\t3V3",
  "2\tGND\tGND",
  "3\tSDI\tI/O\tSDA/MOSI\t3V3",
].join("\n");

test("a pasted pin table is saved, read back, and narrowed by a function", async ({ page }) => {
  const stamp = `${test.info().project.name}-${Date.now()}`;
  const category = `Sensors ${stamp}`;
  const part = `BME280 ${stamp}`;

  await page.goto("/categories");
  await page.getByLabel("Add a category").fill(category);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name: category })).toBeVisible();

  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Parts" })
    .click();
  await page.getByRole("link", { name: "New part" }).click();
  await page.getByLabel("Category").selectOption({ label: category });
  await page.getByLabel("Name", { exact: true }).fill(part);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: part })).toBeVisible();

  // A part arrives with no pins, and its pinout section is where they are written
  // (requirement 5.2).
  const pinout = page.getByRole("region", { name: "Pinout" });
  await expect(pinout).toContainText("No pinout yet.");
  await pinout.getByRole("button", { name: "Add a pinout" }).click();

  // A forty-pin board is a paste, not forty forms. The header is skipped and the rows are
  // shown for review before they touch the table (requirements 6.2, 6.3).
  const editor = page.getByRole("region", { name: "Edit the pinout" });
  await editor.getByRole("button", { name: "Paste a table" }).click();
  await editor.getByRole("textbox", { name: "Pasted table" }).fill(PASTED);

  await expect(editor.getByRole("table", { name: "Pasted pins" }).getByRole("row")).toHaveCount(4);
  await expect(editor.getByText("Lines read: 3")).toBeVisible();

  await editor.getByRole("button", { name: "Replace the table" }).click();

  // `PWR` and `I/O` are mapped, `SDA/MOSI` shared one cell, and the short row kept the pin
  // it named with the rest empty (requirements 6.4, 6.5, 6.7, 6.8).
  await expect(editor.getByRole("combobox", { name: "Pin 1, type" })).toHaveValue("power");
  await expect(editor.getByRole("textbox", { name: "Pin 2, voltage" })).toHaveValue("");
  await expect(editor.getByRole("textbox", { name: "Pin 3, label" })).toHaveValue("SDI");
  await expect(editor.getByRole("textbox", { name: "Pin 3, alternate functions" })).toHaveValue(
    "SDA MOSI",
  );

  await editor.getByRole("button", { name: "Save the pinout" }).click();

  // Saved, the table reads back in the order it was pasted, the volts shown as a level
  // (requirements 1.1, 2.13, 5.1).
  await expect(pinout.getByRole("row")).toHaveCount(4);
  const sdi = pinout.getByRole("row").filter({ hasText: "SDI" });
  await expect(sdi).toContainText("I/O");
  await expect(sdi).toContainText("3.3V");

  // `SDA` is in no label: it is an alternate function of the pin labelled `SDI`
  // (requirement 5.3).
  await pinout.getByRole("searchbox", { name: "Filter pins" }).fill("SDA");
  await expect(pinout.getByRole("row")).toHaveCount(2);
  await expect(pinout).not.toContainText("VDD");
});
