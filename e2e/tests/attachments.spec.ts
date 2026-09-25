import { expect, test } from "@playwright/test";

/**
 * Attachments end to end, on the local file store: a part is filed, a tiny PDF and a tiny
 * PNG generated in the test are uploaded to it, both show in the list with the PNG as an
 * image preview, the PDF opens inline in a new tab and downloads, and the PNG is removed
 * after the confirmation.
 *
 * It reuses the session auth.setup.ts saved, like every other journey. The local database
 * keeps what a run creates, so the names carry a stamp.
 */

/** The smallest thing the API sniffs as a PDF: the `%PDF-` header is all it reads. */
function tinyPdf(): Buffer {
  return Buffer.from(
    "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n" +
      "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n" +
      "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 72 72]>>endobj\n" +
      "trailer<</Root 1 0 R>>\n%%EOF\n",
    "latin1",
  );
}

/** A 1x1 transparent PNG, byte for byte, so the API sniffs the PNG signature. */
function tinyPng(): Buffer {
  return Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC",
    "base64",
  );
}

test("upload a PDF and a PNG to a part, open the PDF, download it, remove the PNG", async ({
  page,
}) => {
  const stamp = `${test.info().project.name}-${Date.now()}`;
  const category = `Attachable ${stamp}`;
  const part = `ATmega ${stamp}`;
  const pdfName = `datasheet-${stamp}.pdf`;
  const pngName = `photo-${stamp}.png`;

  // A part to hang the files on.
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

  const attachments = page.getByRole("region", { name: "Attachments" });
  await expect(attachments.getByText("No attachments yet.")).toBeVisible();

  // The file input is hidden behind the drop zone; picking a file is what a drop does too.
  const picker = attachments.locator('input[type="file"]');

  // Upload the PDF: its kind is guessed as a datasheet, its title taken from the file name.
  await picker.setInputFiles({
    name: pdfName,
    mimeType: "application/pdf",
    buffer: tinyPdf(),
  });
  await attachments.getByRole("button", { name: "Add attachment" }).click();
  const pdfRow = attachments.getByRole("listitem").filter({ hasText: pdfName });
  await expect(pdfRow).toBeVisible();
  await expect(pdfRow).toContainText("Datasheet");

  // Upload the PNG: guessed as an image, shown as a small preview (requirement 6.1).
  await picker.setInputFiles({
    name: pngName,
    mimeType: "image/png",
    buffer: tinyPng(),
  });
  await attachments.getByRole("button", { name: "Add attachment" }).click();
  const pngRow = attachments.getByRole("listitem").filter({ hasText: pngName });
  await expect(pngRow).toBeVisible();
  await expect(pngRow).toContainText("Image");
  await expect(pngRow.getByRole("img", { name: `Preview of ${pngName}` })).toBeVisible();

  // Opening the PDF opens it in a new tab (requirement 6.4); the link points at the content
  // route, which the browser is meant to show inline rather than download.
  const openLink = pdfRow.getByRole("link", { name: `Open ${pdfName}` });
  await expect(openLink).toHaveAttribute("target", "_blank");
  const contentUrl = await openLink.evaluate((link) => (link as HTMLAnchorElement).href);
  const popupPromise = page.waitForEvent("popup");
  await openLink.click();
  await (await popupPromise).close();

  // The content route serves the PDF's own bytes inline with its media type, not as a
  // download (requirements 3.1, 3.2). The request carries the session's cookies.
  const inline = await page.request.get(contentUrl);
  expect(inline.status()).toBe(200);
  expect(inline.headers()["content-type"]).toContain("application/pdf");
  expect(inline.headers()["content-disposition"]).toContain("inline");

  // Downloading the PDF sends it as an attachment the browser saves (requirements 3.2, 6.4).
  const downloadPromise = page.waitForEvent("download");
  await pdfRow.getByRole("link", { name: `Download ${pdfName}` }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toContain(".pdf");

  // Removing the PNG asks first, then takes the row away (requirements 4.2, 6.5).
  await pngRow.getByRole("button", { name: `Remove ${pngName}` }).click();
  await pngRow.getByRole("button", { name: "Remove attachment" }).click();
  await expect(attachments.getByRole("listitem").filter({ hasText: pngName })).toHaveCount(0);

  // The PDF is untouched: removing one leaves the rest (requirement 4.2).
  await expect(attachments.getByRole("listitem").filter({ hasText: pdfName })).toBeVisible();
});
