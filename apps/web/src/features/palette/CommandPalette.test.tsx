import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SearchGroup } from "@wiredex/api-client";
import { delay, HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderInRouter, renderWithProviders } from "../../test/render";
import {
  aCategory,
  aLocation,
  aSearchHit,
  respondAsLoggedIn,
  respondWithActivity,
  respondWithApiVersion,
  respondWithCategories,
  respondWithCategorySchema,
  respondWithLocations,
  respondWithShortRevisions,
  respondWithTiedUpParts,
  respondWithWorkspaceSearch,
  server,
} from "../../test/server";
import { QuickAddProvider } from "../inventory/intake/QuickAddProvider";
import { PaletteProvider, usePalette } from "./PaletteProvider";

const SENSOR = aSearchHit({
  id: "0199cccc-0000-7000-8000-0000000000a1",
  title: "BME280 sensor",
  detail: "Bosch · BME280",
});
const BOARD = aSearchHit({
  id: "0199cccc-0000-7000-8000-0000000000a2",
  title: "WX-U-0007",
  detail: "BME280 sensor",
});
const SHELF = aSearchHit({
  id: "0199ffff-0000-7000-8000-0000000000a3",
  title: "Sensor shelf",
  detail: "WX-L-0007",
});
const SENSORS = aSearchHit({ id: "0199bbbb-0000-7000-8000-0000000000a4", title: "Sensors" });
const STATION = aSearchHit({
  id: "0199eeee-0000-7000-8000-0000000000b1",
  title: "Sensor station",
  detail: "esp32",
});
const LOGGER = aSearchHit({
  id: "0199eeee-0000-7000-8000-0000000000b2",
  title: "Sensor logger",
  detail: "esp32:esp32:esp32",
});
const FOUND: SearchGroup[] = [
  { kind: "part", hits: [SENSOR], more: true },
  { kind: "unit", hits: [BOARD], more: false },
  { kind: "category", hits: [SENSORS], more: false },
  { kind: "location", hits: [SHELF], more: false },
];
const EVERY_KIND: SearchGroup[] = [
  { kind: "part", hits: [SENSOR], more: false },
  { kind: "unit", hits: [BOARD], more: false },
  { kind: "project", hits: [STATION], more: false },
  { kind: "firmware", hits: [LOGGER], more: false },
  { kind: "category", hits: [SENSORS], more: false },
  { kind: "location", hits: [SHELF], more: false },
];

/** A page with a button that opens the palette, under both providers, as the layout has them. */
function Page() {
  const palette = usePalette();
  return (
    <>
      <button type="button" onClick={() => palette.open()}>
        Open the palette
      </button>
      <label>
        Notes <input type="text" />
      </label>
    </>
  );
}

function renderPalette(language: "en" | "pt-BR" = "en") {
  respondWithCategories([aCategory({ name: "Resistors" })]);
  respondWithCategorySchema(aCategory({ name: "Resistors" }), []);
  respondWithLocations([aLocation()]);
  return renderInRouter(
    <QuickAddProvider>
      <PaletteProvider>
        <Page />
      </PaletteProvider>
    </QuickAddProvider>,
    { language },
  );
}

async function openPalette() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Open the palette" }));
  const dialog = await screen.findByRole("dialog", { name: "Search and commands" });
  return { user, dialog, box: within(dialog).getByRole("combobox", { name: "Search Wiredex" }) };
}

function optionNames(): string[] {
  const list = screen.getByRole("listbox", { name: /^(Choices|Opções)$/ });
  return within(list)
    .getAllByRole("option")
    .map((option) => option.textContent ?? "");
}

describe("PaletteProvider", () => {
  it("opens on Ctrl K, even from a text field, with focus in its box", async () => {
    renderPalette();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("textbox", { name: "Notes" }));

    await user.keyboard("{Control>}k{/Control}");

    const dialog = await screen.findByRole("dialog", { name: "Search and commands" });
    expect(within(dialog).getByRole("combobox", { name: "Search Wiredex" })).toHaveFocus();
  });

  it("opens on ⌘ K too, and never twice", async () => {
    renderPalette();
    const user = userEvent.setup();
    await screen.findByRole("button", { name: "Open the palette" });

    await user.keyboard("{Meta>}k{/Meta}");
    await screen.findByRole("dialog", { name: "Search and commands" });
    await user.keyboard("{Control>}k{/Control}");

    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("ignores other chords and never opens over another dialog", async () => {
    renderPalette();
    const user = userEvent.setup();
    await screen.findByRole("button", { name: "Open the palette" });

    await user.keyboard("{Control>}{Shift>}k{/Shift}{/Control}");
    await user.keyboard("k");
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.keyboard("{Alt>}n{/Alt}");
    await screen.findByRole("dialog", { name: "Quick add" });
    await user.keyboard("{Control>}k{/Control}");
    expect(screen.queryByRole("dialog", { name: "Search and commands" })).toBeNull();
  });

  it("keeps the page behind out of reach, and Escape hands focus back", async () => {
    // Requirements 3.3 and 3.4.
    renderPalette();
    const { user } = await openPalette();
    const opener = screen.getByRole("button", { name: "Open the palette", hidden: true });
    expect(opener.closest("[inert]")).not.toBeNull();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Open the palette" })).toHaveFocus();
  });

  it("closes from its backdrop", async () => {
    renderPalette();
    const { user } = await openPalette();

    await user.click(screen.getByRole("button", { name: "Close the search" }));

    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("CommandPalette", () => {
  it("lists every command while the box is empty, and filters them as the text is typed", async () => {
    // Requirements 4.1 and 4.2.
    respondWithWorkspaceSearch([]);
    renderPalette();
    const { user, box } = await openPalette();

    expect(optionNames()).toHaveLength(15);
    expect(optionNames()[0]).toBe("Go to the Dashboard");
    expect(screen.getByRole("status")).toHaveTextContent("15 choices");

    await user.type(box, "new");

    expect(optionNames()).toEqual(["New part", "New project", "New firmware"]);
  });

  it("runs a command with Enter, opening its page", async () => {
    respondWithWorkspaceSearch([]);
    const { router } = renderPalette();
    const { user, box } = await openPalette();

    await user.type(box, "trash");
    await user.keyboard("{Enter}");

    expect(screen.queryByRole("dialog")).toBeNull();
    await expect.poll(() => router.state.location.pathname).toBe("/trash");
  });

  it("runs quick-add from its command, focus in quick-add's first field", async () => {
    respondWithWorkspaceSearch([]);
    renderPalette();
    const { user, box } = await openPalette();

    await user.type(box, "quick add");
    await user.keyboard("{Enter}");

    const quickAdd = await screen.findByRole("dialog", { name: "Quick add" });
    expect(screen.queryByRole("dialog", { name: "Search and commands" })).toBeNull();
    expect(within(quickAdd).getAllByRole("combobox")[0]).toHaveFocus();
  });

  it("finds records once typing pauses, a group per kind, each hit with its detail", async () => {
    // Requirements 4.2 and 4.5.
    const asked = respondWithWorkspaceSearch(FOUND);
    renderPalette();
    const { user, box } = await openPalette();

    await user.type(box, "sensor");

    const parts = await screen.findByRole("group", { name: "Parts · more match, keep typing" });
    expect(
      within(parts).getByRole("option", { name: "BME280 sensor Bosch · BME280" }),
    ).toBeVisible();
    expect(screen.getByRole("group", { name: "Units" })).toHaveTextContent("WX-U-0007");
    expect(screen.getByRole("group", { name: "Categories" })).toHaveTextContent("Sensors");
    expect(screen.getByRole("group", { name: "Locations" })).toHaveTextContent("WX-L-0007");
    expect(screen.getByRole("status")).toHaveTextContent("4 choices");
    // Once, for the whole word: the box waits for typing to pause before it asks.
    expect(asked).toEqual(["sensor"]);
  });

  it("moves with the arrows, wrapping around, and opens the active hit", async () => {
    // Requirements 4.3 and 4.4.
    respondWithWorkspaceSearch(FOUND);
    const { router } = renderPalette();
    const { user, box } = await openPalette();

    await user.type(box, "sensor");
    await screen.findByRole("group", { name: /^Parts/ });
    const first = screen.getByRole("option", { name: /^BME280 sensor/ });
    expect(first).toHaveAttribute("aria-selected", "true");
    expect(box).toHaveAttribute("aria-activedescendant", first.id);

    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("option", { name: /^Sensor shelf/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(screen.getByRole("option", { name: /^WX-U-0007/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    await user.keyboard("{Enter}");

    await expect.poll(() => router.state.location.pathname).toBe(`/units/${BOARD.id}`);
  });

  it.each([
    [/^BME280 sensor/, `/parts/${SENSOR.id}`, {}],
    [/^WX-U-0007/, `/units/${BOARD.id}`, {}],
    [/^Sensor station/, `/projects/${STATION.id}`, {}],
    [/^Sensor logger/, `/firmware/${LOGGER.id}`, {}],
    [/^Sensors/, "/parts", { category: SENSORS.id }],
    [/^Sensor shelf/, "/locations", { selected: SHELF.id }],
  ])("opens %s where it is used", async (name, pathname, search) => {
    // Requirement 4.4: a record's own page; a category's parts; a location, selected.
    respondWithWorkspaceSearch(EVERY_KIND);
    const { router } = renderPalette();
    const { user, box } = await openPalette();

    await user.type(box, "sensor");
    await user.click(await screen.findByRole("option", { name }));

    await expect.poll(() => router.state.location.pathname).toBe(pathname);
    expect(router.state.location.search).toEqual(search);
  });

  it("says so when nothing matches", async () => {
    respondWithWorkspaceSearch([]);
    renderPalette();
    const { user, box } = await openPalette();

    await user.type(box, "zzz");

    expect(await screen.findByText("Nothing matches “zzz”.")).toBeVisible();
    expect(screen.queryByRole("listbox", { name: "Choices" })).toBeNull();
  });

  it("says so while the search is asked, and when it fails, the commands still there", async () => {
    server.use(
      http.get("*/api/search", async () => {
        await delay(300);
        return HttpResponse.json({}, { status: 500 });
      }),
    );
    renderPalette();
    const { user, box } = await openPalette();

    await user.type(box, "trash");

    expect(screen.getByRole("status")).toHaveTextContent("Searching…");
    expect(await screen.findByText(/The search couldn't be done\./)).toBeVisible();
    expect(optionNames()).toEqual(["Go to the Trash"]);
  });

  it("speaks Brazilian Portuguese", async () => {
    respondWithWorkspaceSearch(FOUND);
    renderPalette("pt-BR");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Open the palette" }));
    const dialog = await screen.findByRole("dialog", { name: "Busca e comandos" });
    const box = within(dialog).getByRole("combobox", { name: "Buscar no Wiredex" });

    expect(optionNames()[0]).toBe("Ir para o Painel");
    await user.type(box, "sensor");

    expect(
      await screen.findByRole("group", { name: "Peças · há mais, continue digitando" }),
    ).toBeVisible();
    expect(screen.getByRole("group", { name: "Locais" })).toBeVisible();
  });
});

describe("the header's search button", () => {
  it("opens the palette and names its shortcut", async () => {
    respondWithApiVersion("0.0.0");
    respondAsLoggedIn();
    respondWithTiedUpParts([]);
    respondWithShortRevisions([]);
    respondWithActivity([]);
    const queryClient = createTestQueryClient();
    const history = createMemoryHistory({ initialEntries: ["/"] });
    renderWithProviders(<RouterProvider router={createAppRouter(queryClient, history)} />, {
      queryClient,
    });
    const button = await screen.findByRole("button", { name: "Search" });
    expect(button).toHaveAttribute("aria-keyshortcuts", "Control+K Meta+K");
    expect(button).toHaveTextContent("Ctrl K");

    await userEvent.setup().click(button);

    expect(await screen.findByRole("dialog", { name: "Search and commands" })).toBeVisible();
  });
});
