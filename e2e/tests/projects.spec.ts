import { expect, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";

/**
 * Projects and revisions end to end: a project is created with tags, its first revision A is
 * given a summary, a Gerber archive is attached to A, a revision B is forked from A, the
 * project opens on the latest (B), a photo is added to the project, the list narrows by tag
 * and by text, A is deleted while B stays (the only revision can't go), and the project is
 * deleted.
 *
 * It reuses the session auth.setup.ts saved, like every other journey. The local database
 * keeps what a run creates, so every name carries a stamp.
 */

/** The smallest thing the API sniffs as a ZIP: the `PK\x03\x04` local file header is all it
 * reads (files/domain/values.py). A few trailing bytes stand in for an archive's body. */
function tinyZip(): Buffer {
  return Buffer.concat([Buffer.from("PK\x03\x04", "latin1"), Buffer.alloc(26)]);
}

/** A 1x1 transparent PNG, byte for byte, so the API sniffs the PNG signature. */
function tinyPng(): Buffer {
  return Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC",
    "base64",
  );
}

test("create a project with tags, fork a revision, add files and photos, narrow the list, delete", async ({
  page,
}) => {
  const stamp = `${test.info().project.name}-${Date.now()}`;
  const project = `Weather station ${stamp}`;
  const zipName = `gerbers-${stamp}.zip`;
  const photoName = `board-${stamp}.png`;

  const nav = page.getByRole("navigation", { name: "Main navigation" });

  // From the navigation, New project: a name, a description and the tags ESP32 and i2c, typed
  // as a person would — ESP32 then Enter, i2c then a comma. Both fold to lower case, and the
  // project opens on revision A, a draft.
  await page.goto("/");
  await nav.getByRole("link", { name: "Projects" }).click();
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();

  await page.getByRole("link", { name: "New project" }).click();
  await expect(page.getByRole("heading", { name: "New project" })).toBeVisible();

  await page.getByLabel("Name", { exact: true }).fill(project);
  await page.getByLabel("Description").fill("A BME280 on an ESP32, logging every five minutes.");
  const tagBox = page.getByRole("combobox", { name: "Tags" });
  await tagBox.fill("ESP32");
  await tagBox.press("Enter");
  await tagBox.pressSequentially("i2c,");

  const chosen = page.getByRole("list", { name: "Chosen tags" });
  await expect(chosen.getByText("esp32")).toBeVisible();
  await expect(chosen.getByText("i2c")).toBeVisible();

  await page.getByRole("button", { name: "Save" }).click();

  // The project page opens on revision A, a draft, carrying both folded tags.
  await expect(page.getByRole("heading", { name: project })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Revision A", exact: true })).toBeVisible();
  const revisionA = page.getByRole("region", { name: "Revision A" });
  await expect(revisionA.getByText("Draft")).toBeVisible();
  const projectTags = page.getByRole("list", { name: "Tags" });
  await expect(projectTags.getByRole("link", { name: "esp32" })).toBeVisible();
  await expect(projectTags.getByRole("link", { name: "i2c" })).toBeVisible();

  // Edit revision A: a summary, so the panel reads `Revision A – breadboard`.
  await page.getByRole("button", { name: "Edit revision" }).click();
  const editDialog = page.getByRole("dialog", { name: "Edit revision A" });
  await editDialog.getByLabel("Summary").fill("breadboard");
  await editDialog.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: "Revision A – breadboard" })).toBeVisible();

  // On A's Files, a Gerber archive: the drop zone suggests Gerbers for a ZIP, and its row
  // offers Download but no Open (the API always serves a ZIP as a download).
  const files = page.getByRole("region", { name: "Files" });
  await expect(files.getByText("No files yet.")).toBeVisible();
  const revisionPicker = files.locator('input[type="file"]');
  await revisionPicker.setInputFiles({
    name: zipName,
    mimeType: "application/zip",
    buffer: tinyZip(),
  });
  await expect(files.getByLabel("Kind")).toHaveValue("gerbers");
  // The chosen file's long name is cut short in its box rather than widening the page.
  await expectNoSidewaysScroll(page);
  await files.getByRole("button", { name: "Add attachment" }).click();

  const zipRow = files.getByRole("listitem").filter({ hasText: zipName });
  await expect(zipRow).toBeVisible();
  await expect(zipRow).toContainText("Gerbers");
  await expect(zipRow.getByRole("link", { name: `Download ${zipName}` })).toBeVisible();
  await expect(zipRow.getByRole("link", { name: `Open ${zipName}` })).toHaveCount(0);

  // Fork A: the label is prefilled B, and a summary. The fork opens, says Forked from A, and
  // its own Files are empty; the Revisions navigation lists A and B, with B the open one.
  await page.getByRole("button", { name: "Fork", exact: true }).click();
  const forkDialog = page.getByRole("dialog", { name: "Fork revision A – breadboard" });
  await expect(forkDialog.getByLabel("Label")).toHaveValue("B");
  await forkDialog.getByLabel("Summary").fill("perfboard");
  await forkDialog.getByRole("button", { name: "Fork", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Revision B – perfboard" })).toBeVisible();
  const revisionB = page.getByRole("region", { name: "Revision B – perfboard" });
  await expect(revisionB.getByText("Forked from")).toBeVisible();
  await expect(revisionB.getByRole("link", { name: "A", exact: true })).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Files" }).getByText("No files yet."),
  ).toBeVisible();

  const revisions = page.getByRole("navigation", { name: "Revisions" });
  await expect(revisions.getByRole("link", { name: /A – breadboard/ })).toBeVisible();
  const bLink = revisions.getByRole("link", { name: /B – perfboard/ });
  await expect(bLink).toBeVisible();
  await expect(bLink).toHaveAttribute("aria-current", "page");

  // The project's own address opens the latest revision, B.
  const projectUrl = new URL(page.url());
  await page.goto(`${projectUrl.pathname.replace(/\/revisions\/.*$/, "")}`);
  await expect(page.getByRole("heading", { name: "Revision B – perfboard" })).toBeVisible();

  // A photo on the project: the gallery shows it, its title its text alternative.
  const photos = page.getByRole("region", { name: "Photos" });
  await expect(photos.getByText("No photos yet.")).toBeVisible();
  const photoPicker = photos.locator('input[type="file"]');
  await photoPicker.setInputFiles({
    name: photoName,
    mimeType: "image/png",
    buffer: tinyPng(),
  });
  await photos.getByRole("button", { name: "Add photo" }).click();
  await expect(photos.getByRole("img", { name: photoName })).toBeVisible();

  // The projects list narrows by tag and by text, and shows an empty state when nothing
  // matches. The i2c chip and a search for the stamp each keep the project.
  await nav.getByRole("link", { name: "Projects" }).click();
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();

  const row = page.getByRole("row").filter({ hasText: project });
  await page.getByRole("button", { name: /^i2c \(/ }).click();
  await expect(row).toBeVisible();

  await page.getByRole("searchbox", { name: "Search projects by name" }).fill(project);
  await expect(row).toBeVisible();

  await page.getByRole("searchbox", { name: "Search projects by name" }).fill(`Nowhere ${stamp}`);
  await expect(page.getByText("No project matches this search.")).toBeVisible();

  // Open A and delete it: B stays, and its own Delete revision is unavailable, saying a
  // project keeps one revision.
  await page.goto(projectUrl.pathname);
  await revisions.getByRole("link", { name: /A – breadboard/ }).click();
  await expect(page.getByRole("heading", { name: "Revision A – breadboard" })).toBeVisible();

  await page.getByRole("button", { name: "Delete revision" }).click();
  await page.getByRole("button", { name: "Yes, delete it" }).click();

  // B is left, the latest, and now the project's only revision: its delete is disabled.
  await expect(page.getByRole("heading", { name: "Revision B – perfboard" })).toBeVisible();
  const deleteRevision = page.getByRole("button", { name: "Delete revision" });
  await expect(deleteRevision).toHaveAttribute("aria-disabled", "true");
  await expect(
    page.getByText("A project keeps at least one revision; move the project to the trash instead."),
  ).toBeVisible();

  // Move the project to the trash: the list no longer shows it.
  await page.getByRole("button", { name: "Move to trash" }).click();
  await page.getByRole("button", { name: "Yes, move it" }).click();

  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: project })).toHaveCount(0);
});
