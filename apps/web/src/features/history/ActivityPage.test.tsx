import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { HistoryChange } from "@wiredex/api-client";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aChange,
  acceptRestores,
  aRowChange,
  respondAsLoggedIn,
  respondWithActivity,
  respondWithApiVersion,
  server,
} from "../../test/server";
import { historyKeys } from "./history";

const RENAME = aChange();
const PINOUT = aChange({
  id: 40,
  occurred_at: "2026-10-01T17:00:00Z",
  actor: null,
  record: { kind: "part", id: "0199aaaa-0000-7000-8000-0000000000f2", label: "BME280" },
  rows: [
    aRowChange({
      kind: "pin",
      operation: "insert",
      label: "3 SDA",
      fields: [
        { name: "label", before: null, after: "SDA" },
        { name: "number", before: null, after: "3" },
      ],
    }),
  ],
  more_rows: 24,
  restorable: false,
});
const GONE = aChange({
  id: 39,
  occurred_at: "2026-10-01T16:00:00Z",
  action: "deleted",
  record: { kind: "project", id: "0199aaaa-0000-7000-8000-0000000000f3", label: "Old robot" },
  rows: [aRowChange({ kind: "project", operation: "delete", label: "Old robot", fields: [] })],
  restorable: false,
});
const SKETCH = Array.from({ length: 12 }, (_, line) => `// line ${line} of the sketch`).join("\n");
const SOURCE = aChange({
  id: 38,
  record: { kind: "firmware", id: "0199aaaa-0000-7000-8000-0000000000f4", label: "Weather" },
  rows: [
    aRowChange({
      kind: "source_file",
      operation: "insert",
      label: "main.cpp",
      fields: [
        { name: "content", before: null, after: SKETCH },
        { name: "path", before: null, after: "main.cpp" },
      ],
    }),
  ],
  restorable: false,
});

function renderActivity(language: "en" | "pt-BR" = "en") {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: ["/activity"] });
  renderWithProviders(<RouterProvider router={createAppRouter(queryClient, history)} />, {
    queryClient,
    language,
  });
  return queryClient;
}

async function items(): Promise<HTMLElement[]> {
  const main = await screen.findByRole("main");
  const list = await within(main).findByRole("list", { name: /^(Changes|Alterações)$/ });
  return within(list)
    .getAllByRole("listitem")
    .filter((item) => item.parentElement === list);
}

describe("ActivityPage", () => {
  it("folds each change to what happened, who, when and one line of what it changed", async () => {
    respondWithActivity([RENAME, PINOUT, GONE, SOURCE]);
    renderActivity();

    expect(await screen.findByRole("heading", { name: "Activity", level: 1 })).toBeVisible();
    const [rename, pinout, gone, source] = (await items()) as [
      HTMLElement,
      HTMLElement,
      HTMLElement,
      HTMLElement,
    ];
    expect(rename).toHaveTextContent("Edited");
    expect(rename).toHaveTextContent("by Owner");
    expect(within(rename).getByRole("link", { name: "Part 4.7 kΩ 1% 0805" })).toHaveAttribute(
      "href",
      `/parts/${RENAME.record.id}`,
    );
    expect(within(rename).getByText("Part number: RC0805FR-074K7 → RC0805FR-074K7L")).toBeVisible();
    expect(pinout).toHaveTextContent("by Wiredex");
    expect(within(pinout).getByText("25 changes: Pin 3 SDA")).toBeVisible();
    // A record deleted for good has no page to link to.
    expect(gone).toHaveTextContent("Deleted");
    expect(within(gone).queryByRole("link")).toBeNull();
    expect(within(gone).getByText("Project Old robot removed")).toBeVisible();
    expect(within(source).getByText("Source file main.cpp added")).toBeVisible();
    // Folded, nothing but the toggle is offered: no rows, no fields, no restore.
    for (const item of [rename, pinout, gone, source]) {
      const toggle = within(item).getByRole("button");
      expect(toggle).toHaveAccessibleName("Expand");
      expect(toggle).toHaveAttribute("title", "Expand");
      expect(toggle).toHaveAttribute("aria-expanded", "false");
    }
    expect(screen.queryByRole("button", { name: /Restore/ })).toBeNull();
    expect(screen.getByText(/History starts with Wiredex 0\.8\.0/)).toBeVisible();
  });

  it("opens a change to its rows and fields, and folds it again", async () => {
    respondWithActivity([RENAME, PINOUT]);
    renderActivity();
    const user = userEvent.setup();
    const [rename, pinout] = (await items()) as [HTMLElement, HTMLElement];

    await user.click(within(rename).getByRole("button", { name: "Expand" }));

    const collapse = within(rename).getByRole("button", { name: "Collapse" });
    expect(collapse).toHaveAttribute("aria-expanded", "true");
    expect(collapse).toHaveAttribute("title", "Collapse");
    const detail = document.getElementById(collapse.getAttribute("aria-controls") ?? "");
    expect(detail).toBeVisible();
    expect(within(detail as HTMLElement).getByText("Part number")).toBeVisible();
    expect(detail).toHaveTextContent("RC0805FR-074K7 → RC0805FR-074K7L");
    expect(
      within(rename).getByRole("button", { name: "Restore the version before this change" }),
    ).toBeVisible();

    await user.click(within(pinout).getByRole("button", { name: "Expand" }));
    expect(pinout).toHaveTextContent("Pin 3 SDA added");
    expect(pinout).toHaveTextContent("And 24 more changes in this save.");
    // Not restorable, so only its toggle is offered.
    expect(within(pinout).getAllByRole("button")).toHaveLength(1);

    await user.click(collapse);
    expect(within(rename).getByRole("button", { name: "Expand" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(detail).not.toBeVisible();
    expect(within(rename).queryByText("Part number")).toBeNull();
  });

  it("keeps a long value on one line folded, and in a box of its own opened", async () => {
    respondWithActivity([SOURCE]);
    renderActivity();
    const user = userEvent.setup();
    const [source] = (await items()) as [HTMLElement];

    expect(within(source).queryByRole("group")).toBeNull();
    await user.click(within(source).getByRole("button", { name: "Expand" }));

    const box = within(source).getByRole("group", { name: "Text, after" });
    expect(box).toHaveTextContent("// line 11 of the sketch");
    expect(box).toHaveAttribute("tabindex", "0");
    // A short value next to it reads as it is, without a box.
    expect(within(source).queryByRole("group", { name: "Path, after" })).toBeNull();
  });

  it("spreads the blocks over two columns on a wide screen, each keeping its own height", async () => {
    respondWithActivity([RENAME, PINOUT]);
    renderActivity();

    const list = await within(await screen.findByRole("main")).findByRole("list", {
      name: "Changes",
    });
    expect(list).toHaveClass("xl:grid-cols-2", "xl:items-start");
  });

  it("reads more on request", async () => {
    const many: HistoryChange[] = Array.from({ length: 52 }, (_, index) =>
      aChange({ id: 100 - index, restorable: false }),
    );
    respondWithActivity(many);
    renderActivity();

    expect(await items()).toHaveLength(50);
    expect(screen.queryByText(/History starts with/)).toBeNull();
    await userEvent.setup().click(screen.getByRole("button", { name: "Show more" }));

    await expect.poll(async () => (await items()).length).toBe(52);
    expect(screen.getByText(/History starts with/)).toBeVisible();
  });

  it("says when nothing has changed yet", async () => {
    respondWithActivity([]);
    renderActivity();

    expect(await screen.findByText("Nothing has changed yet.")).toBeVisible();
    expect(screen.getByText(/History starts with/)).toBeVisible();
  });

  it("says so when the activity can't be read", async () => {
    server.use(http.get("*/api/history", () => HttpResponse.json({}, { status: 500 })));
    renderActivity();

    expect(await screen.findByRole("alert")).toHaveTextContent("The activity couldn't be loaded.");
  });

  it("asks before restoring, and keeps the version on cancel", async () => {
    respondWithActivity([RENAME]);
    const restored = acceptRestores();
    renderActivity();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Expand" }));
    await user.click(
      screen.getByRole("button", { name: "Restore the version before this change" }),
    );
    const question = screen.getByRole("group", { name: /Put 4\.7 kΩ 1% 0805 back as it was/ });
    await user.click(within(question).getByRole("button", { name: "Keep it" }));

    expect(restored).toEqual([]);
    expect(
      screen.getByRole("button", { name: "Restore the version before this change" }),
    ).toBeVisible();
  });

  it("restores a version and refreshes the record and history", async () => {
    respondWithActivity([RENAME]);
    const restored = acceptRestores();
    const queryClient = renderActivity();
    queryClient.setQueryData(["catalog", "part", RENAME.record.id], { id: RENAME.record.id });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Expand" }));
    await user.click(
      screen.getByRole("button", { name: "Restore the version before this change" }),
    );
    await user.click(screen.getByRole("button", { name: "Restore" }));

    expect(await screen.findByText("Restored. The restore is the newest change.")).toBeVisible();
    expect(restored).toEqual([RENAME.id]);
    expect(queryClient.getQueryState(["catalog", "part", RENAME.record.id])?.isInvalidated).toBe(
      true,
    );
    expect(queryClient.getQueryState(historyKeys.feed)?.dataUpdateCount).toBeGreaterThan(1);
  });

  it("says why a restore was refused, beside its change", async () => {
    respondWithActivity([RENAME]);
    acceptRestores({ refuse: "another part already uses that MPN" });
    renderActivity();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Expand" }));
    await user.click(
      screen.getByRole("button", { name: "Restore the version before this change" }),
    );
    await user.click(screen.getByRole("button", { name: "Restore" }));

    const [change] = await items();
    expect(await within(change as HTMLElement).findByRole("alert")).toHaveTextContent(
      "This version couldn't be restored: another part already uses that MPN",
    );
  });

  it("speaks Brazilian Portuguese", async () => {
    respondWithActivity([RENAME, SOURCE]);
    renderActivity("pt-BR");
    const user = userEvent.setup();

    expect(await screen.findByRole("heading", { name: "Atividade", level: 1 })).toBeVisible();
    const [rename, source] = (await items()) as [HTMLElement, HTMLElement];
    expect(rename).toHaveTextContent("Editado");
    expect(rename).toHaveTextContent("por Owner");
    expect(
      within(rename).getByText("Código do fabricante: RC0805FR-074K7 → RC0805FR-074K7L"),
    ).toBeVisible();
    expect(within(source).getByText("Inclusão: Arquivo de código main.cpp")).toBeVisible();

    await user.click(within(rename).getByRole("button", { name: "Expandir" }));
    expect(within(rename).getByRole("button", { name: "Recolher" })).toHaveAttribute(
      "title",
      "Recolher",
    );
    expect(within(rename).getByText("Código do fabricante")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Restaurar a versão de antes desta alteração" }),
    ).toBeVisible();
  });
});
