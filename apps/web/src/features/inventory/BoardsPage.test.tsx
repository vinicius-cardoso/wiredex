import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { UnitResponse } from "@wiredex/api-client";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aRevisionRef,
  aUnit,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithBoardList,
  respondWithBoardParts,
  respondWithRevisionRefs,
  server,
} from "../../test/server";
import { validateBoardSearch } from "./units";

const SENSOR_PART = "0199cccc-0000-7000-8000-0000000000a9";
const BUILD = aRevisionRef({
  id: "0199eeee-0000-7000-8000-0000000000b7",
  project_id: "0199eeee-0000-7000-8000-0000000000b0",
  project_name: "Robot",
});

const built = aUnit({
  id: "0199dddd-0000-7000-8000-0000000000c3",
  code: "WX-U-0003",
  part_name: "ESP32 DevKit",
  serial: "SN-3",
  mac: "aa:bb:cc:dd:ee:03",
  status: "in_use",
  revision_id: BUILD.id,
  location: null,
});
const retired = aUnit({
  id: "0199dddd-0000-7000-8000-0000000000c2",
  code: "WX-U-0002",
  part_name: "ESP32 DevKit",
  status: "retired",
});
const sensor = aUnit({
  id: "0199dddd-0000-7000-8000-0000000000c1",
  code: "WX-U-0001",
  part_id: SENSOR_PART,
  part_name: "BME280 breakout",
  serial: "BME-1",
});
const BOARDS = [built, retired, sensor];

function renderBoards(
  initial = "/units",
  boards: UnitResponse[] = BOARDS,
  language: "en" | "pt-BR" = "en",
) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  const asked = respondWithBoardList(boards);
  const refsAsked = respondWithRevisionRefs([BUILD]);
  const queryClient = createTestQueryClient();
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [initial] }));
  renderWithProviders(<RouterProvider router={router} />, { queryClient, language });
  return { router, asked, refsAsked };
}

async function codes(): Promise<string[]> {
  const table = await screen.findByRole("table", { name: "Boards" });
  return within(table)
    .getAllByRole("rowheader")
    .map((cell) => cell.textContent ?? "");
}

describe("BoardsPage", () => {
  it("lists every board with its part, identity, status, place and build", async () => {
    const { refsAsked } = renderBoards();

    expect(await screen.findByRole("heading", { name: "Boards", level: 1 })).toBeVisible();
    expect(await codes()).toEqual(["WX-U-0003", "WX-U-0002", "WX-U-0001"]);
    const row = screen.getByRole("row", { name: /WX-U-0003/ });
    expect(within(row).getByRole("link", { name: "WX-U-0003" })).toHaveAttribute(
      "href",
      `/units/${built.id}`,
    );
    expect(within(row).getByRole("link", { name: "ESP32 DevKit" })).toHaveAttribute(
      "href",
      `/parts/${built.part_id}`,
    );
    expect(row).toHaveTextContent("SN-3");
    expect(row).toHaveTextContent("aa:bb:cc:dd:ee:03");
    expect(row).toHaveTextContent("In use");
    // The build holding it, named in one request for every held board on the page.
    expect(await within(row).findByRole("link", { name: "Robot · A" })).toHaveAttribute(
      "href",
      `/projects/${BUILD.project_id}/revisions/${BUILD.id}`,
    );
    expect(refsAsked).toEqual([[BUILD.id]]);
    const placed = screen.getByRole("row", { name: /WX-U-0001/ });
    expect(placed).toHaveTextContent(`${sensor.location?.name} ${sensor.location?.code}`);
    expect(placed).toHaveTextContent("In stock");
  });

  it("narrows by a code, serial or MAC as it is typed, kept in the address", async () => {
    const { router, asked } = renderBoards();
    const user = userEvent.setup();

    await user.type(
      await screen.findByRole("searchbox", { name: "Search by code, serial or MAC" }),
      "bme",
    );

    await waitFor(() => expect(router.state.location.search).toEqual({ q: "bme" }));
    await waitFor(async () => expect(await codes()).toEqual(["WX-U-0001"]));
    expect(asked).toContain("search=bme");
  });

  it("narrows by status and part, and clears them in one go", async () => {
    const { router } = renderBoards();
    const user = userEvent.setup();

    const status = await screen.findByRole("combobox", { name: "Status" });
    await user.selectOptions(status, "Retired");
    await waitFor(() => expect(router.state.location.search).toEqual({ status: "retired" }));
    await waitFor(async () => expect(await codes()).toEqual(["WX-U-0002"]));

    await user.selectOptions(status, "Any status");
    const part = screen.getByRole("combobox", { name: "Part" });
    // The parts the bench's boards are of, by name.
    expect(
      within(part)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Any part", "BME280 breakout", "ESP32 DevKit"]);
    await user.selectOptions(part, "BME280 breakout");
    await waitFor(() => expect(router.state.location.search).toEqual({ part: SENSOR_PART }));
    await waitFor(async () => expect(await codes()).toEqual(["WX-U-0001"]));

    await user.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(router.state.location.search).toEqual({}));
    await waitFor(async () => expect(await codes()).toHaveLength(3));
    expect(screen.queryByRole("button", { name: "Clear" })).toBeNull();
  });

  it("offers every board's part, one with no board among the rows shown included", async () => {
    renderBoards("/units?status=retired");
    const nano = "0199cccc-0000-7000-8000-0000000000b1";
    const asked = respondWithBoardParts([
      { part_id: nano, part_name: "Arduino Nano", units: 4 },
      { part_id: SENSOR_PART, part_name: "BME280 breakout", units: 1 },
      { part_id: built.part_id, part_name: "ESP32 DevKit", units: 2 },
    ]);

    expect(await codes()).toEqual(["WX-U-0002"]);
    const part = screen.getByRole("combobox", { name: "Part" });
    await waitFor(() =>
      expect(
        within(part)
          .getAllByRole("option")
          .map((option) => option.textContent),
      ).toEqual(["Any part", "Arduino Nano", "BME280 breakout", "ESP32 DevKit"]),
    );
    // Read once, on its own: the list itself isn't asked for every board any more.
    expect(asked).toEqual([""]);
  });

  it("keeps offering the chosen part when no board is of it", async () => {
    const gone = "0199cccc-0000-7000-8000-0000000000b2";
    renderBoards(`/units?part=${gone}`);

    expect(await screen.findByText("No board matches these filters.")).toBeVisible();
    const part = screen.getByRole("combobox", { name: "Part" });
    expect(part).toHaveValue(gone);
    expect(within(part).getByRole("option", { name: "Unknown part" })).toHaveValue(gone);
  });

  it("opens narrowed from a bookmarked address", async () => {
    renderBoards(`/units?status=in_use&part=${built.part_id}`);

    expect(await codes()).toEqual(["WX-U-0003"]);
    expect(screen.getByRole("combobox", { name: "Status" })).toHaveValue("in_use");
    expect(screen.getByRole("combobox", { name: "Part" })).toHaveValue(built.part_id);
  });

  it("says nothing matches when the filters narrow every board away", async () => {
    renderBoards("/units?q=nothing-like-this");

    expect(await screen.findByText("No board matches these filters.")).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("says when the bench has no boards yet", async () => {
    renderBoards("/units", []);

    expect(await screen.findByText(/No boards yet\./)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Clear" })).toBeNull();
  });

  it("says when it shows only the newest two hundred", async () => {
    const many = Array.from({ length: 200 }, (_, index) =>
      aUnit({
        id: `0199dddd-0000-7000-8000-${String(index).padStart(12, "0")}`,
        code: `WX-U-${String(index).padStart(4, "0")}`,
      }),
    );
    renderBoards("/units", many);

    expect(
      await screen.findByText("Showing the newest 200 boards. Narrow the list to find older ones."),
    ).toBeVisible();
  });

  it("says so when the boards can't be read", async () => {
    renderBoards();
    server.use(http.get("*/api/inventory/units", () => HttpResponse.json({}, { status: 500 })));

    expect(await screen.findByRole("alert")).toHaveTextContent("The boards couldn't be loaded.");
  });

  it("names a board whose part the catalog no longer holds", async () => {
    renderBoards("/units", [aUnit({ part_name: null })]);

    expect(await screen.findByRole("link", { name: "Unknown part" })).toBeVisible();
  });

  it("speaks Brazilian Portuguese", async () => {
    renderBoards("/units", BOARDS, "pt-BR");

    expect(await screen.findByRole("heading", { name: "Placas", level: 1 })).toBeVisible();
    const nav = screen.getByRole("navigation", { name: "Navegação principal" });
    expect(within(nav).getByRole("link", { name: "Placas" })).toHaveAttribute("href", "/units");
    expect(
      screen.getByRole("searchbox", { name: "Buscar por código, número de série ou MAC" }),
    ).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Situação" })).toBeVisible();
  });
});

describe("validateBoardSearch", () => {
  it("keeps what fits and drops the rest", () => {
    expect(validateBoardSearch({ q: "  wx ", status: "retired", part: " p1 " })).toEqual({
      q: "wx",
      status: "retired",
      part: "p1",
    });
    expect(validateBoardSearch({ q: 3, status: "melted", part: "" })).toEqual({});
  });
});
