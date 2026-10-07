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

function renderActivity(language: "en" | "pt-BR" = "en", initial = "/activity") {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: [initial] });
  const router = createAppRouter(queryClient, history);
  renderWithProviders(<RouterProvider router={router} />, { queryClient, language });
  return { queryClient, router };
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

  it("keeps the blocks in one column, in the order things happened", async () => {
    respondWithActivity([RENAME, PINOUT]);
    renderActivity();

    const list = await within(await screen.findByRole("main")).findByRole("list", {
      name: "Changes",
    });
    expect(list.className).not.toMatch(/grid-cols/);
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
  });

  it("says when nothing has changed yet", async () => {
    respondWithActivity([]);
    renderActivity();

    expect(await screen.findByText("Nothing has changed yet.")).toBeVisible();
    expect(screen.getByText(/History starts with/)).toBeVisible();
    // Nothing to page: the empty list says so on its own.
    expect(screen.queryByRole("navigation", { name: "Pages of the activity" })).toBeNull();
  });

  it("says so when the activity can't be read", async () => {
    server.use(http.get("*/api/history", () => HttpResponse.json({}, { status: 500 })));
    renderActivity();

    expect(await screen.findByRole("alert")).toHaveTextContent("The activity couldn't be loaded.");
  });

  it("asks the API for one action and one kind at once, keeping them in the address", async () => {
    const asked = respondWithActivity([RENAME, PINOUT, GONE, SOURCE]);
    const { router } = renderActivity();
    const user = userEvent.setup();
    await items();

    await user.selectOptions(screen.getByRole("combobox", { name: "What happened" }), "Deleted");
    await user.selectOptions(screen.getByRole("combobox", { name: "Kind of record" }), "Project");

    await expect.poll(async () => (await items()).length).toBe(1);
    expect(router.state.location.search).toEqual({ action: "deleted", kind: "project" });
    expect(asked.at(-1)).toEqual({
      action: "deleted",
      kind: "project",
      q: null,
      page: 1,
      page_size: 25,
    });
  });

  it("searches the record names once typing pauses, and clears back to everything", async () => {
    respondWithActivity([RENAME, PINOUT, GONE, SOURCE]);
    const { router } = renderActivity();
    const user = userEvent.setup();
    await items();

    await user.type(screen.getByRole("searchbox", { name: "Search by record name" }), "robot");

    await expect.poll(async () => (await items()).length).toBe(1);
    expect(router.state.location.search).toEqual({ q: "robot" });

    await user.click(screen.getByRole("button", { name: "Clear" }));

    await expect.poll(async () => (await items()).length).toBe(4);
    expect(router.state.location.search).toEqual({});
  });

  it("says when no change matches the filters", async () => {
    respondWithActivity([RENAME]);
    renderActivity("en", "/activity?kind=location");

    expect(await screen.findByText("No change matches these filters.")).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Kind of record" })).toHaveValue("location");
    expect(screen.queryByText("Nothing has changed yet.")).toBeNull();
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
    const { queryClient } = renderActivity();
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
    expect(queryClient.getQueryState(historyKeys.feed())?.dataUpdateCount).toBeGreaterThan(1);
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

describe("ActivityPage in pages", () => {
  const MANY: HistoryChange[] = Array.from({ length: 60 }, (_, index) =>
    aChange({ id: 1000 - index, restorable: false }),
  );

  function bar(): HTMLElement {
    return screen.getByRole("navigation", { name: "Pages of the activity" });
  }

  it("shows the first 25 of 60 changes, with the range and no note on where history starts", async () => {
    const asked = respondWithActivity(MANY);
    renderActivity();

    expect(await items()).toHaveLength(25);
    expect(within(bar()).getByText("1–25 of 60")).toBeVisible();
    expect(within(bar()).getByRole("button", { name: "Page 1" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.queryByText(/History starts with/)).toBeNull();
    expect(asked.at(-1)).toMatchObject({ page: 1, page_size: 25 });
  });

  it("asks for the next page, puts it in the address, and Back returns", async () => {
    const asked = respondWithActivity(MANY);
    const { router } = renderActivity();
    const user = userEvent.setup();
    await items();

    await user.click(within(bar()).getByRole("button", { name: "Next page" }));

    expect(await within(bar()).findByText("26–50 of 60")).toBeVisible();
    expect(router.state.location.search).toEqual({ page: 2 });
    expect(asked.at(-1)).toMatchObject({ page: 2, page_size: 25 });
    expect((await items())[0]).toHaveTextContent("Edited");

    router.history.back();

    expect(await within(bar()).findByText("1–25 of 60")).toBeVisible();
    expect(router.state.location.search).toEqual({});
  });

  it("notes where history starts on the last page only", async () => {
    respondWithActivity(MANY);
    renderActivity("en", "/activity?page=3");

    await expect.poll(async () => (await items()).length).toBe(10);
    expect(within(bar()).getByText("51–60 of 60")).toBeVisible();
    expect(screen.getByText(/History starts with/)).toBeVisible();
    expect(within(bar()).getByRole("button", { name: "Next page" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("asks for the page size chosen and keeps it in the address", async () => {
    const asked = respondWithActivity(MANY);
    const { router } = renderActivity();
    const user = userEvent.setup();
    await items();

    await user.selectOptions(within(bar()).getByRole("combobox", { name: "Per page" }), "50");

    await expect.poll(async () => (await items()).length).toBe(50);
    expect(router.state.location.search).toEqual({ size: 50 });
    expect(asked.at(-1)).toMatchObject({ page: 1, page_size: 50 });
  });

  it("goes back to page 1 at the same size when a filter changes", async () => {
    respondWithActivity(MANY);
    const { router } = renderActivity("en", "/activity?page=2&size=50");
    const user = userEvent.setup();
    expect(await within(await screen.findByRole("main")).findByText("51–60 of 60")).toBeVisible();

    await user.selectOptions(screen.getByRole("combobox", { name: "What happened" }), "Edited");

    await expect.poll(() => router.state.location.search).toEqual({ action: "edited", size: 50 });
    expect(await within(bar()).findByText("1–50 of 60")).toBeVisible();
  });

  it("opens the last page when the address asks for one past the end", async () => {
    respondWithActivity(MANY);
    const { router } = renderActivity("en", "/activity?page=9");

    await expect.poll(() => router.state.location.search).toEqual({ page: 3 });
    expect(await within(bar()).findByText("51–60 of 60")).toBeVisible();
  });

  it("opens the first page for a page or size it can't read", async () => {
    const asked = respondWithActivity(MANY);
    renderActivity("en", "/activity?page=abc&size=7");

    expect(await items()).toHaveLength(25);
    expect(asked.at(-1)).toMatchObject({ page: 1, page_size: 25 });
  });

  it("names its bar in Brazilian Portuguese", async () => {
    respondWithActivity(MANY);
    renderActivity("pt-BR");

    await items();
    const nav = screen.getByRole("navigation", { name: "Páginas da atividade" });
    expect(within(nav).getByText("1–25 de 60")).toBeVisible();
  });
});
