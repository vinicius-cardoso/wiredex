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
  it("lists the changes newest first, with who, what and each field before and after", async () => {
    respondWithActivity([RENAME, PINOUT, GONE]);
    renderActivity();

    expect(await screen.findByRole("heading", { name: "Activity", level: 1 })).toBeVisible();
    const [rename, pinout, gone] = await items();
    expect(rename).toHaveTextContent("Edited");
    expect(rename).toHaveTextContent("by Owner");
    expect(within(rename as HTMLElement).getByText("Part number")).toBeVisible();
    expect(rename).toHaveTextContent("RC0805FR-074K7");
    expect(rename).toHaveTextContent("RC0805FR-074K7L");
    expect(
      within(rename as HTMLElement).getByRole("link", { name: "Part 4.7 kΩ 1% 0805" }),
    ).toHaveAttribute("href", `/parts/${RENAME.record.id}`);
    expect(pinout).toHaveTextContent("by Wiredex");
    expect(pinout).toHaveTextContent("Pin 3 SDA added");
    expect(pinout).toHaveTextContent("And 24 more changes in this save.");
    expect(within(pinout as HTMLElement).queryByRole("button")).toBeNull();
    // A record deleted for good has no page to link to.
    expect(gone).toHaveTextContent("Deleted");
    expect(within(gone as HTMLElement).queryByRole("link")).toBeNull();
    expect(screen.getByText(/History starts with Wiredex 0\.8\.0/)).toBeVisible();
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

    await user.click(
      await screen.findByRole("button", { name: "Restore the version before this change" }),
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

    await user.click(
      await screen.findByRole("button", { name: "Restore the version before this change" }),
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

    await user.click(
      await screen.findByRole("button", { name: "Restore the version before this change" }),
    );
    await user.click(screen.getByRole("button", { name: "Restore" }));

    const [change] = await items();
    expect(await within(change as HTMLElement).findByRole("alert")).toHaveTextContent(
      "This version couldn't be restored: another part already uses that MPN",
    );
  });

  it("speaks Brazilian Portuguese", async () => {
    respondWithActivity([RENAME]);
    renderActivity("pt-BR");

    expect(await screen.findByRole("heading", { name: "Atividade", level: 1 })).toBeVisible();
    const [rename] = await items();
    expect(rename).toHaveTextContent("Editado");
    expect(rename).toHaveTextContent("por Owner");
    expect(within(rename as HTMLElement).getByText("Código do fabricante")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Restaurar a versão de antes desta alteração" }),
    ).toBeVisible();
  });
});
