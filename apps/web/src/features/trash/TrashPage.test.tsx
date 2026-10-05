import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { TrashedItem } from "@wiredex/api-client";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  acceptTrashWrites,
  aTrashedItem,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithTrash,
  server,
} from "../../test/server";

const PART = aTrashedItem();
const UNIT = aTrashedItem({
  kind: "unit",
  id: "0199aaaa-0000-7000-8000-0000000000e2",
  name: "WX-U-0007",
  detail: "ESP32-DevKitC",
  trashed_at: "2026-10-01T09:20:00Z",
});
const PROJECT = aTrashedItem({
  kind: "project",
  id: "0199aaaa-0000-7000-8000-0000000000e3",
  name: "Weather station",
  detail: null,
  trashed_at: "2026-10-01T09:10:00Z",
});
const FIRMWARE = aTrashedItem({
  kind: "firmware",
  id: "0199aaaa-0000-7000-8000-0000000000e4",
  name: "Station sketch",
  detail: "esp32:esp32:esp32",
  trashed_at: "2026-10-01T09:00:00Z",
});

function renderTrash(language: "en" | "pt-BR" = "en", initial = "/trash") {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: [initial] });
  const router = createAppRouter(queryClient, history);
  renderWithProviders(<RouterProvider router={router} />, { queryClient, language });
  return router;
}

async function rows(): Promise<HTMLElement[]> {
  const table = await screen.findByRole("table", { name: "Trash" });
  // The header row first, then one row per record.
  return within(table).getAllByRole("row").slice(1);
}

/** The page's own notices, apart from the footer's version badge, which is a status too. */
function notices(): HTMLElement {
  return within(screen.getByRole("main")).getByRole("status");
}

function rowOf(name: string): HTMLElement {
  const cell = screen.getByRole("rowheader", { name });
  const row = cell.closest("tr");
  if (!row) throw new Error(`no row for ${name}`);
  return row;
}

describe("TrashPage", () => {
  it("lists what is in the trash in order, with each record's kind and detail", async () => {
    respondWithTrash([PART, UNIT, PROJECT, FIRMWARE]);
    renderTrash();

    expect(await screen.findByRole("heading", { name: "Trash", level: 1 })).toBeInTheDocument();
    const listed = await rows();
    expect(listed.map((row) => within(row).getByRole("rowheader").textContent)).toEqual([
      "BME280 breakout",
      "WX-U-0007",
      "Weather station",
      "Station sketch",
    ]);
    expect(listed[0]).toHaveTextContent("Part");
    expect(listed[0]).toHaveTextContent("BME280");
    expect(listed[1]).toHaveTextContent("Unit");
    expect(listed[1]).toHaveTextContent("ESP32-DevKitC");
    expect(listed[2]).toHaveTextContent("Project");
    expect(listed[3]).toHaveTextContent("Firmware");
    expect(listed[3]).toHaveTextContent("esp32:esp32:esp32");
    expect(within(listed[0] as HTMLElement).getByText(/2026/)).toHaveAttribute(
      "datetime",
      PART.trashed_at,
    );
  });

  it("says when the trash is empty, and offers nothing to empty", async () => {
    respondWithTrash([]);
    renderTrash();

    expect(await screen.findByText("The trash is empty.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Empty the trash" })).not.toBeInTheDocument();
  });

  it("says so when the trash can't be read", async () => {
    server.use(http.get("*/api/trash", () => HttpResponse.json({}, { status: 500 })));
    renderTrash();

    expect(await screen.findByRole("alert")).toHaveTextContent("The trash couldn't be loaded.");
  });

  it("narrows by a kind at once, keeping it in the address", async () => {
    const trash = respondWithTrash([PART, UNIT, PROJECT, FIRMWARE]);
    const router = renderTrash();
    await rows();

    await userEvent
      .setup()
      .selectOptions(screen.getByRole("combobox", { name: "Kind" }), "Project");

    await expect.poll(async () => (await rows()).length).toBe(1);
    expect(rowOf("Weather station")).toBeInTheDocument();
    expect(router.state.location.search).toEqual({ kind: "project" });
    expect(trash.asked.at(-1)).toEqual({ kind: "project", q: null, page: 1, page_size: 50 });
  });

  it("narrows by a name or detail once typing pauses, and clears back to everything", async () => {
    const user = userEvent.setup();
    respondWithTrash([PART, UNIT, PROJECT, FIRMWARE]);
    const router = renderTrash();
    await rows();

    await user.type(screen.getByRole("searchbox", { name: "Search by name or detail" }), "esp32");

    // The board's detail and the sketch's target both hold it.
    await expect
      .poll(async () => (await rows()).map((row) => within(row).getByRole("rowheader").textContent))
      .toEqual(["WX-U-0007", "Station sketch"]);
    expect(router.state.location.search).toEqual({ q: "esp32" });

    await user.click(screen.getByRole("button", { name: "Clear" }));

    await expect.poll(async () => (await rows()).length).toBe(4);
    expect(router.state.location.search).toEqual({});
    expect(screen.getByRole("searchbox", { name: "Search by name or detail" })).toHaveValue("");
  });

  it("says when nothing matches, still offering to empty the whole trash", async () => {
    respondWithTrash([PART, PROJECT]);
    renderTrash("en", "/trash?q=nothing-like-this");

    expect(
      await screen.findByText("Nothing in the trash matches these filters."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Empty the trash" })).toBeInTheDocument();
  });

  it("offers no clearing while nothing narrows the list", async () => {
    respondWithTrash([PART]);
    renderTrash();
    await rows();

    expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();
  });

  it("restores a record, takes it off the list and links to it", async () => {
    const trash = respondWithTrash([PART, PROJECT]);
    const writes = acceptTrashWrites(trash);
    const router = renderTrash();
    await rows();

    await userEvent.setup().click(screen.getByRole("button", { name: "Restore Weather station" }));

    const notice = notices();
    await expect.poll(() => notice.textContent).toContain("Weather station is back.");
    expect(writes.restored).toEqual([`project:${PROJECT.id}`]);
    await expect.poll(async () => (await rows()).length).toBe(1);
    const link = within(notice).getByRole("link", { name: "Open Weather station" });
    expect(link).toHaveAttribute("href", `/projects/${PROJECT.id}`);
    expect(router.state.location.pathname).toBe("/trash");
  });

  it.each([
    [PART, "/parts/"],
    [UNIT, "/units/"],
    [FIRMWARE, "/firmware/"],
  ])("links a restored %s to its own page", async (item, path) => {
    acceptTrashWrites(respondWithTrash([item]));
    renderTrash();
    await rows();

    await userEvent.setup().click(screen.getByRole("button", { name: `Restore ${item.name}` }));

    const link = await screen.findByRole("link", { name: `Open ${item.name}` });
    expect(link).toHaveAttribute("href", `${path}${item.id}`);
  });

  it("says a restore didn't happen, and drops a record no longer in the trash", async () => {
    const trash = respondWithTrash([PART, UNIT]);
    acceptTrashWrites(trash);
    renderTrash();
    await rows();
    trash.held = [UNIT]; // restored elsewhere meanwhile

    await userEvent.setup().click(screen.getByRole("button", { name: "Restore BME280 breakout" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("That couldn't be restored.");
    await expect.poll(async () => (await rows()).length).toBe(1);
    expect(screen.queryByRole("rowheader", { name: "BME280 breakout" })).not.toBeInTheDocument();
    expect(notices()).toHaveTextContent("");
  });

  it("asks in the row before deleting for good, and keeps the record on cancel", async () => {
    const writes = acceptTrashWrites(respondWithTrash([PART, UNIT]));
    renderTrash();
    await rows();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Delete WX-U-0007 for good" }));
    const question = within(rowOf("WX-U-0007")).getByRole("group", {
      name: "Delete WX-U-0007 for good? This can't be undone.",
    });
    await user.click(within(question).getByRole("button", { name: "Keep it" }));

    expect(writes.deleted).toEqual([]);
    expect(
      within(rowOf("WX-U-0007")).getByRole("button", { name: "Delete WX-U-0007 for good" }),
    ).toBeInTheDocument();
  });

  it("deletes a record for good once asked", async () => {
    const writes = acceptTrashWrites(respondWithTrash([PART, UNIT]));
    renderTrash();
    await rows();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Delete WX-U-0007 for good" }));
    await user.click(within(rowOf("WX-U-0007")).getByRole("button", { name: "Delete for good" }));

    await expect.poll(async () => (await rows()).length).toBe(1);
    expect(writes.deleted).toEqual([`unit:${UNIT.id}`]);
    expect(screen.queryByRole("rowheader", { name: "WX-U-0007" })).not.toBeInTheDocument();
  });

  it("says a delete for good didn't happen, and keeps the record listed", async () => {
    respondWithTrash([PART]);
    server.use(
      http.delete("*/api/trash/:kind/:itemId", () => HttpResponse.json({}, { status: 500 })),
    );
    renderTrash();
    await rows();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Delete BME280 breakout for good" }));
    await user.click(screen.getByRole("button", { name: "Delete for good" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("That couldn't be deleted.");
    expect(screen.getByRole("rowheader", { name: "BME280 breakout" })).toBeInTheDocument();
  });

  it("asks before emptying the trash, then says it is empty", async () => {
    const writes = acceptTrashWrites(respondWithTrash([PART, UNIT, PROJECT, FIRMWARE]));
    renderTrash();
    await rows();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Empty the trash" }));
    const question = screen.getByRole("group", {
      name: "Delete everything in the trash for good? This can't be undone.",
    });
    await user.click(within(question).getByRole("button", { name: "Keep it all" }));
    expect(writes.emptied).toBe(0);

    await user.click(screen.getByRole("button", { name: "Empty the trash" }));
    await user.click(
      within(screen.getByRole("group", { name: /Delete everything/ })).getByRole("button", {
        name: "Empty the trash",
      }),
    );

    expect(await screen.findByText("The trash is empty.")).toBeInTheDocument();
    expect(writes.emptied).toBe(1);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("says when the trash couldn't be emptied", async () => {
    respondWithTrash([PART]);
    server.use(http.delete("*/api/trash", () => HttpResponse.json({}, { status: 500 })));
    renderTrash();
    await rows();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Empty the trash" }));
    await user.click(
      within(screen.getByRole("group", { name: /Delete everything/ })).getByRole("button", {
        name: "Empty the trash",
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("The trash couldn't be emptied.");
  });

  it("speaks Brazilian Portuguese", async () => {
    respondWithTrash([PROJECT]);
    renderTrash("pt-BR");

    expect(await screen.findByRole("heading", { name: "Lixeira", level: 1 })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Restaurar Weather station" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Excluir Weather station de vez" })).toBeVisible();
    expect(rowOf("Weather station")).toHaveTextContent("Projeto");
  });
});

describe("TrashPage in pages", () => {
  function many(count: number): TrashedItem[] {
    return Array.from({ length: count }, (_, index) =>
      aTrashedItem({
        id: `0199aaaa-0000-7000-8000-${String(index).padStart(12, "0")}`,
        name: `Part ${index}`,
      }),
    );
  }

  function bar(name = "Pages of the trash"): HTMLElement {
    return screen.getByRole("navigation", { name });
  }

  it("shows the first 50 records with the range, and asks for the first page", async () => {
    const trash = respondWithTrash(many(52));
    renderTrash();

    expect(await rows()).toHaveLength(50);
    expect(within(bar()).getByText("1–50 of 52")).toBeVisible();
    expect(within(bar()).getByRole("button", { name: "Page 1" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(trash.asked.at(-1)).toMatchObject({ page: 1, page_size: 50 });
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("asks for the next page, puts it in the address, and Back returns", async () => {
    const trash = respondWithTrash(many(52));
    const router = renderTrash();
    await rows();

    await userEvent.setup().click(within(bar()).getByRole("button", { name: "Next page" }));

    expect(await within(bar()).findByText("51–52 of 52")).toBeVisible();
    expect(router.state.location.search).toEqual({ page: 2 });
    expect(trash.asked.at(-1)).toMatchObject({ page: 2, page_size: 50 });
    await expect.poll(async () => (await rows()).length).toBe(2);
    expect(screen.getByRole("rowheader", { name: "Part 51" })).toBeInTheDocument();

    router.history.back();

    expect(await within(bar()).findByText("1–50 of 52")).toBeVisible();
    expect(router.state.location.search).toEqual({});
  });

  it("goes back to page 1 at the same size when a filter changes", async () => {
    respondWithTrash([...many(52), UNIT]);
    const router = renderTrash("en", "/trash?page=2&size=25");
    expect(await within(await screen.findByRole("main")).findByText("26–50 of 53")).toBeVisible();
    const user = userEvent.setup();

    await user.selectOptions(screen.getByRole("combobox", { name: "Kind" }), "Part");
    await expect.poll(() => router.state.location.search).toEqual({ kind: "part", size: 25 });
    expect(await within(bar()).findByText("1–25 of 52")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Clear" }));
    await expect.poll(() => router.state.location.search).toEqual({ size: 25 });
  });

  it("lands on the page before once the only record of the last page is restored", async () => {
    const items = many(51);
    acceptTrashWrites(respondWithTrash(items));
    const router = renderTrash("en", "/trash?page=2");
    expect(await within(await screen.findByRole("main")).findByText("51–51 of 51")).toBeVisible();

    await userEvent.setup().click(screen.getByRole("button", { name: "Restore Part 50" }));

    await expect.poll(() => router.state.location.search).toEqual({});
    expect(await within(bar()).findByText("1–50 of 50")).toBeVisible();
    await expect.poll(async () => (await rows()).length).toBe(50);
    expect(notices()).toHaveTextContent("Part 50 is back.");
  });

  it("opens the last page when the address asks for one past the end", async () => {
    respondWithTrash(many(52));
    const router = renderTrash("en", "/trash?page=9");

    await expect.poll(() => router.state.location.search).toEqual({ page: 2 });
    expect(await within(bar()).findByText("51–52 of 52")).toBeVisible();
  });

  it("opens the first page for a page or size it can't read", async () => {
    const trash = respondWithTrash(many(52));
    renderTrash("en", "/trash?page=abc&size=7");

    expect(await rows()).toHaveLength(50);
    expect(trash.asked.at(-1)).toMatchObject({ page: 1, page_size: 50 });
  });

  it("names its bar in Brazilian Portuguese", async () => {
    respondWithTrash(many(52));
    renderTrash("pt-BR");

    await screen.findByRole("table", { name: "Lixeira" });
    expect(within(bar("Páginas da lixeira")).getByText("1–50 de 52")).toBeVisible();
  });
});
