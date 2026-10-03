import { expect, test } from "@playwright/test";
import { expectNoSidewaysScroll } from "./layout";

/**
 * The tracked-units end to end: a category is marked tracked-individually, three boards are
 * received into a drawer as units (three WX-U-… codes, the part total 3), one board is given
 * a MAC, moved to a second location, then retired (the total drops to 2). The Boards list
 * holds all three with their part, finds the one again by that MAC, and narrows to it by its
 * status and part. It exercises the whole slice end to end (all requirements).
 *
 * It reuses the session auth.setup.ts saved, like every other journey, and never logs out.
 * The local database keeps what a run creates, so every name and the MAC carry a stamp.
 */
test("mark a category tracked, receive three boards, tag, move, retire and find one", async ({
  page,
}) => {
  const stamp = `${test.info().project.name}-${Date.now()}`;
  const category = `Dev boards ${stamp}`;
  const part = `ESP32 ${stamp}`;
  const drawer = `Drawer ${stamp}`;
  const shelf = `Shelf ${stamp}`;
  // A stamped MAC so the search finds this run's board and no other's. The last three octets
  // carry a slice of the timestamp; the value stays a valid six-octet address. It is typed in
  // an upper-case hyphen spelling, and stored canonical (lower-case, colon-separated), so the
  // preview and the stored form differ and the canonicalization is really exercised.
  const suffix = Date.now().toString(16).padStart(12, "0").slice(-6);
  const canonical = `de:ad:be:${suffix.slice(0, 2)}:${suffix.slice(2, 4)}:${suffix.slice(4, 6)}`;
  const typedMac = canonical.replace(/:/g, "-").toUpperCase();

  // Two locations: one to receive into, one to move a board to (requirements 1.1, 4.1).
  await page.goto("/locations");
  await createLocation(page, drawer);
  await createLocation(page, shelf);

  // A fresh root category, marked tracked-individually, so its parts are received as units
  // rather than a loose lot count (requirements 8.1, and the unit-tracked switch).
  await page.goto("/categories");
  await page.getByLabel("Add a category").fill(category);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const branch = page.getByRole("treeitem", { name: category });
  await expect(branch).toBeVisible();
  await branch.click();

  const selected = page.getByRole("region", { name: `The category ${category}` });
  await selected.getByLabel("Tracked individually").selectOption("yes");

  // A part in that category. Saving lands on the part page, where its stock lives.
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Parts" })
    .click();
  await page.getByRole("link", { name: "New part" }).click();
  await page.getByLabel("Category").selectOption({ label: category });
  await page.getByLabel("Name", { exact: true }).fill(part);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: part })).toBeVisible();

  // A unit-tracked part offers *Receive units*, not the loose *Receive* (requirement 8.1).
  const stock = page.getByRole("region", { name: "Stock" });
  await expect(stock.getByText("0 in stock")).toBeVisible();
  await stock.getByRole("button", { name: "Receive units" }).click();

  // Receive three boards into the drawer: quantity 3 grows to three per-unit rows, each of
  // which could carry a serial or MAC; here they are left blank (requirements 1.1, 8.2).
  const receive = page.getByRole("dialog", { name: "Receive units" });
  await selectLocation(receive.getByLabel("Location"), drawer);
  const quantity = receive.getByLabel("Quantity");
  await quantity.fill("3");
  // Three unit rows can push the confirm button below a short viewport, so submit the form
  // from the quantity field with Enter rather than clicking a button that may be off-screen.
  await quantity.press("Enter");

  // Success shows the three minted codes, of the WX-U-… form (requirements 2.1, 2.2, 8.2).
  await expect(receive.getByText(/Received:/)).toBeVisible();
  const codes = await receive.getByRole("listitem").allTextContents();
  const minted = codes.map((code) => code.trim());
  expect(minted).toHaveLength(3);
  for (const code of minted) expect(code).toMatch(/^WX-U-\d{4,}$/);
  await receive.getByRole("button", { name: "Cancel" }).click();

  // The part total is now three, all three in the drawer (requirements 1.4, 9.1).
  await expect(stock.getByText("3 in stock")).toBeVisible();
  const units = page.getByRole("region", { name: "Units" });
  const [first] = minted;
  for (const code of minted) {
    await expect(units.getByRole("row").filter({ hasText: code })).toContainText("Drawer");
  }

  // Open the first board's own page to tag, move and retire it (requirement 8.3).
  await units.getByRole("link", { name: first }).click();
  await expect(page.getByRole("heading", { name: first })).toBeVisible();

  // Give it a MAC, typed AA-BB-… but stored aa:bb:… The canonical form is previewed once the
  // input validates, then stored (requirements 5.3, 8.5). The dialog is titled with the code.
  await page.getByRole("button", { name: "Relabel" }).click();
  const relabel = page.getByRole("dialog", { name: `Relabel ${first}` });
  await relabel.getByLabel("MAC").fill(typedMac);
  await expect(relabel.getByText(new RegExp(escapeRegExp(canonical)))).toBeVisible();
  await relabel.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(canonical)).toBeVisible();

  // Move it to the shelf; its location follows (requirements 4.1, 4.2).
  await page.getByRole("button", { name: "Move", exact: true }).click();
  const move = page.getByRole("dialog", { name: `Move ${first}` });
  await selectLocation(move.getByLabel("To"), shelf);
  await move.getByRole("button", { name: "Move", exact: true }).click();
  await expect(page.getByRole("definition").filter({ hasText: shelf })).toBeVisible();

  // Retire it; a retired unit stops counting, so its lot drops by one (requirements 3.1, 3.3).
  await page.getByRole("button", { name: "Retire", exact: true }).click();
  const retire = page.getByRole("dialog", { name: `Retire ${first}` });
  await retire.getByRole("button", { name: "Retire", exact: true }).click();
  // Exact: the page's *Firmware* section says a retired unit can't be flashed (spec 15, 8.4).
  await expect(page.getByText("Retired", { exact: true })).toBeVisible();

  // Back on the part page the total is two: the retired board no longer counts (requirement
  // 3.3, 9.1). The other two are still in the drawer.
  await page.goto("/parts");
  await page.getByRole("link", { name: part }).click();
  await expect(page.getByRole("heading", { name: part })).toBeVisible();
  const stockAgain = page.getByRole("region", { name: "Stock" });
  await expect(stockAgain.getByText("2 in stock")).toBeVisible();

  // The Boards list holds every board, the newest first: this run's three, each naming its
  // part (the boards list).
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Boards" })
    .click();
  await expect(page.getByRole("heading", { name: "Boards", level: 1 })).toBeVisible();
  const boards = page.getByRole("table", { name: "Boards" });
  for (const code of minted) {
    await expect(boards.getByRole("row").filter({ hasText: code })).toContainText(part);
  }

  // Find the board again by its MAC: the search matches it as a substring and links to it
  // (requirements 2.5, 6.3, 8.4), kept in the address.
  const search = page.getByRole("searchbox", { name: "Search by code, serial or MAC" });
  await search.fill(canonical);
  await expect(page).toHaveURL(/[?&]q=/);
  const hit = boards.getByRole("row").filter({ hasText: first });
  await expect(hit).toContainText(canonical);
  await expect(hit).toContainText("Retired");
  await expect(hit.getByRole("link", { name: first })).toBeVisible();
  // The heading row and the one board.
  await expect(boards.getByRole("row")).toHaveCount(2);

  // Narrowed to this part's retired boards, the other two drop out; Clear brings back all.
  await search.fill("");
  await page.getByLabel("Status").selectOption({ label: "Retired" });
  await page.getByLabel("Part", { exact: true }).selectOption({ label: part });
  await expect(boards.getByRole("row")).toHaveCount(2);
  await expect(boards.getByRole("row").filter({ hasText: first })).toBeVisible();
  await page.getByRole("button", { name: "Clear" }).click();
  await expect(page).toHaveURL(/\/units$/);
  await expectNoSidewaysScroll(page);
});

/** Adds a top-level location and waits for it to appear in the tree. */
async function createLocation(page: import("@playwright/test").Page, name: string) {
  await page.getByLabel("Add a location").fill(name);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("treeitem", { name })).toBeVisible();
}

/**
 * Picks a location in a unit dialog by the name it was given. The option text is
 * `name (WX-L-NNNN)`, and the short code is minted by the server, so match on the name and
 * select the option by its own value rather than guess the code.
 */
async function selectLocation(combobox: import("@playwright/test").Locator, name: string) {
  const value = await combobox
    .getByRole("option", { name: new RegExp(escapeRegExp(name)) })
    .getAttribute("value");
  if (value === null) throw new Error(`no option for the location ${name}`);
  await combobox.selectOption(value);
}

/** Escapes the stamp so its characters aren't read as a pattern. */
function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
