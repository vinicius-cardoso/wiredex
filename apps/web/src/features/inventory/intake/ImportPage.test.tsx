import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderInRouter } from "../../../test/render";
import {
  aBom,
  aCellProblem,
  acceptImports,
  anImportPreview,
  anImportResult,
  anImportRow,
  anImportSummary,
  aUnit,
  refuseImportPreviewsAsUnreadable,
  refuseImports,
  refuseImportsAsChanged,
  respondWithBom,
  respondWithImportPreviews,
} from "../../../test/server";
import { useBom } from "../../projects/bom/bom";
import { ImportPage } from "./ImportPage";

const SHEET = "categoria;nome;local;quantidade\nResistors;10k 0805;WX-L-0003;200\n";

/** A board row: one unit, labelled, received into Drawer 3. */
const boardRow = anImportRow({
  row: 3,
  part: {
    kind: "existing",
    part_id: "0199cccc-0000-7000-8000-0000000000e1",
    name: "ESP32-DevKitC",
    category: "Boards",
    same_as_row: null,
  },
  stock: {
    ...(anImportRow().stock as NonNullable<ReturnType<typeof anImportRow>["stock"]>),
    kind: "units",
    quantity: 1,
    units: [{ serial: "SN-1", mac: "aa:bb:cc:dd:ee:ff" }],
  },
});

/** Row 4 names a location the tree doesn't hold. */
const badRow = anImportRow({
  row: 4,
  stock: null,
  problems: [
    aCellProblem({
      row: 4,
      column: "location",
      code: "unknown_location",
      message: "no location is Drawer 9",
    }),
  ],
});

/** A BOM open beside the page, as a revision panel in another tab of the app would be. */
function OpenBom() {
  const bom = useBom(aBom().revision_id);
  return <p>{bom.isSuccess ? "BOM loaded" : "BOM loading"}</p>;
}

/** The page inside a router, once it is drawn (the router renders its route after a tick). */
async function renderPage() {
  const user = userEvent.setup();
  renderInRouter(
    <>
      <ImportPage />
      <OpenBom />
    </>,
  );
  await screen.findByRole("heading", { name: "Import from a sheet" });
  return { user };
}

function textBox() {
  return screen.getByRole("textbox", { name: "Sheet text" });
}

function importButton() {
  return screen.getByRole("button", { name: "Import" });
}

async function pasteAndPreview(user: ReturnType<typeof userEvent.setup>, text = SHEET) {
  await user.click(textBox());
  await user.paste(text);
  await user.click(screen.getByRole("button", { name: "Preview" }));
}

describe("ImportPage", () => {
  it("fills the text box with the chosen file, so a cell can be fixed in place", async () => {
    const { user } = await renderPage();
    const file = new File([SHEET], "bench.csv", { type: "text/csv" });

    await user.upload(screen.getByLabelText("Choose a CSV file"), file);

    await waitFor(() => expect(textBox()).toHaveValue(SHEET));
  });

  it("offers the template as a download", async () => {
    await renderPage();
    const link = screen.getByRole("link", { name: "Download the template" });
    expect(link).toHaveAttribute("href", "/api/inventory/imports/template");
    expect(link).toHaveAttribute("download");
  });

  it("shows each row's part, stock and translated problems, and keeps Import off", async () => {
    const sent = respondWithImportPreviews(
      anImportPreview({
        summary: anImportSummary({ rows: 3, rows_with_problems: 1, units: 1 }),
        problems: [
          aCellProblem({
            column: null,
            code: "sheet_too_many_units",
            message: "a sheet receives at most 500 units",
          }),
        ],
        rows: [anImportRow(), boardRow, badRow],
      }),
    );
    const { user } = await renderPage();

    await pasteAndPreview(user);

    const table = await screen.findByRole("table", { name: "What each row of the sheet will do" });
    expect(sent).toEqual([SHEET]);
    const rows = within(table).getAllByRole("row");
    expect(within(rows[1] as HTMLElement).getByRole("rowheader")).toHaveTextContent("2");
    expect(rows[1]).toHaveTextContent("New part10k 0805Passives / Resistors");
    expect(rows[1]).toHaveTextContent("Lot: 200WX-L-0003 Drawer 3");
    expect(
      within(rows[2] as HTMLElement).getByRole("link", { name: "ESP32-DevKitC" }),
    ).toBeVisible();
    expect(rows[2]).toHaveTextContent("Units: 1");
    expect(rows[2]).toHaveTextContent("Serial SN-1 · MAC aa:bb:cc:dd:ee:ff");
    expect(rows[3]).toHaveTextContent("location: That location isn't in the tree.");
    expect(
      screen.getByText("A sheet receives at most 500 units. Split it into two."),
    ).toBeVisible();

    const summary = screen.getByRole("status", { name: "Import summary" });
    expect(summary).toHaveTextContent("The preview found problems.");
    expect(within(summary).getByText("Rows with problems").nextSibling).toHaveTextContent("1");

    expect(importButton()).toHaveAttribute("aria-disabled", "true");
    expect(importButton()).toHaveAccessibleDescription(
      "Fix every problem and preview the sheet again to import it.",
    );
    await waitFor(() => expect(screen.getByRole("heading", { name: "Preview" })).toHaveFocus());
  });

  it("turns Import off again when the text changes after a clean preview", async () => {
    respondWithImportPreviews();
    const sent = acceptImports();
    const { user } = await renderPage();

    await pasteAndPreview(user);

    await waitFor(() => expect(importButton()).toHaveFocus());
    expect(importButton()).not.toHaveAttribute("aria-disabled");
    expect(screen.getByRole("status", { name: "Import summary" })).toHaveTextContent(
      "The preview is clean.",
    );

    await user.type(textBox(), "Resistors;4k7 0805;WX-L-0003;100");

    expect(importButton()).toHaveAttribute("aria-disabled", "true");
    expect(importButton()).toHaveAccessibleDescription(
      "The sheet changed since its preview. Preview it again to import it.",
    );
    await user.click(importButton());
    expect(sent).toEqual([]);
  });

  it("imports a clean preview and shows the summary and the minted unit codes", async () => {
    const digest = "ab".repeat(32);
    respondWithImportPreviews(anImportPreview({ digest }));
    const unit = aUnit({ code: "WX-U-0007", mac: "aa:bb:cc:dd:ee:ff" });
    const sent = acceptImports(
      anImportResult({ summary: anImportSummary({ rows: 2, units: 1 }), units: [unit] }),
    );
    const { user } = await renderPage();

    await pasteAndPreview(user);
    await waitFor(() => expect(importButton()).toHaveFocus());
    await user.click(importButton());

    const heading = await screen.findByRole("heading", { name: "Imported" });
    await waitFor(() => expect(heading).toHaveFocus());
    expect(sent).toEqual([{ csv: SHEET, digest }]);
    const summary = screen.getByRole("status", { name: "Import summary" });
    expect(summary).toHaveTextContent("The sheet is imported.");
    expect(within(summary).getByText("Units").nextSibling).toHaveTextContent("1");
    const codes = screen.getByRole("list", { name: "Unit codes" });
    expect(within(codes).getByRole("link", { name: "WX-U-0007" })).toBeVisible();
    const parts = screen.getByRole("list", { name: "Parts defined" });
    expect(within(parts).getByRole("link", { name: "Row 2: 10k 0805" })).toBeVisible();
    // Importing again takes a new preview, so the same sheet isn't stocked twice by a click.
    expect(screen.queryByRole("button", { name: "Import" })).not.toBeInTheDocument();
  });

  it("fetches an open bill of materials again once the sheet is imported", async () => {
    const reads = respondWithBom(aBom());
    respondWithImportPreviews(anImportPreview({ digest: "cd".repeat(32) }));
    acceptImports();
    const { user } = await renderPage();
    await screen.findByText("BOM loaded");
    expect(reads).toHaveLength(1);

    await pasteAndPreview(user);
    await waitFor(() => expect(importButton()).toHaveFocus());
    await user.click(importButton());

    await screen.findByRole("heading", { name: "Imported" });
    await expect.poll(() => reads.length).toBe(2);
  });

  it("says when the outcome changed since the preview, and previews again", async () => {
    const previews = respondWithImportPreviews();
    refuseImportsAsChanged();
    const { user } = await renderPage();

    await pasteAndPreview(user);
    await waitFor(() => expect(importButton()).toHaveFocus());
    await user.click(importButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "What this sheet would do changed since its preview, so nothing was imported.",
    );
    const again = screen.getByRole("button", { name: "Preview again" });
    await waitFor(() => expect(again).toHaveFocus());

    await user.click(again);

    await waitFor(() => expect(previews).toEqual([SHEET, SHEET]));
    await waitFor(() => expect(importButton()).toHaveFocus());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("lists the problems an import found since its preview", async () => {
    respondWithImportPreviews();
    refuseImports([badRow.problems[0] as NonNullable<(typeof badRow.problems)[0]>]);
    const { user } = await renderPage();

    await pasteAndPreview(user);
    await waitFor(() => expect(importButton()).toHaveFocus());
    await user.click(importButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The sheet has problems now, so nothing was imported.",
    );
    expect(screen.getByText("That location isn't in the tree.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Preview again" })).toBeVisible();
  });

  it("says why a sheet can't be read, in the reader's language", async () => {
    refuseImportPreviewsAsUnreadable(
      "unknown_column",
      "'colour' is neither a column like name or quantity nor an attribute key like resistance",
      "colour",
    );
    const { user } = await renderPage();

    await pasteAndPreview(user, "colour,name\nred,LED\n");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "“colour” is neither a column like name or quantity nor an attribute key like resistance.",
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Import" })).not.toBeInTheDocument();
  });

  it("asks for a sheet before previewing nothing", async () => {
    const sent = respondWithImportPreviews();
    const { user } = await renderPage();

    await user.click(screen.getByRole("button", { name: "Preview" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Choose a file or paste a sheet first.");
    expect(sent).toEqual([]);
  });
});
