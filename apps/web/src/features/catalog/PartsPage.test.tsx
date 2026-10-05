import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FacetsResponse } from "@wiredex/api-client";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aCategory,
  anAttribute,
  aSearchResult,
  refuseSearch,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithCategories,
  respondWithCategorySchema,
  respondWithFacets,
  respondWithPartTotals,
  respondWithSearch,
  server,
} from "../../test/server";

const passives = aCategory({ name: "Passives", part_count: 2 });
const resistors = aCategory({
  id: "0199bbbb-0000-7000-8000-000000000002",
  parent_id: passives.id,
  name: "Resistors",
});
const resistance = anAttribute({
  category_id: resistors.id,
  key: "resistance",
  label: "Resistance",
  kind: "number",
  unit: "Ω",
});

const noFacets: FacetsResponse = { enums: {}, bools: {}, numbers: {} };

const resistor = aSearchResult({
  name: "4.7 kΩ 1% 0805",
  category_id: resistors.id,
  attributes: { resistance: { value: "4700", display: "4.7k", unit: "Ω" } },
});
const microcontroller = aSearchResult({
  id: "0199cccc-0000-7000-8000-000000000002",
  name: "ATmega328P",
  category_id: passives.id,
  manufacturer: "Microchip",
  mpn: "ATMEGA328P-PU",
  package: "DIP-28",
});

function renderPartsPage(initial = "/parts") {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  respondWithCategories([passives, resistors]);
  respondWithCategorySchema(resistors, [resistance]);
  respondWithFacets(resistors, noFacets);
  // The list asks the batch route for each shown part's total; the resistor holds 42. The
  // returned array records the ids each request asked about, so a test can check batching.
  const askedForTotals = respondWithPartTotals([{ part_id: resistor.id, on_hand: 42 }]);
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: [initial] });
  const router = createAppRouter(queryClient, history);
  renderWithProviders(<RouterProvider router={router} />, { queryClient });
  return { router, askedForTotals };
}

function partNames(): string[] {
  return screen.queryAllByRole("rowheader").map((cell) => cell.textContent ?? "");
}

describe("PartsPage", () => {
  it("lists every part with its category", async () => {
    respondWithSearch([resistor, microcontroller]);
    renderPartsPage();

    expect(await screen.findByRole("rowheader", { name: resistor.name })).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(3); // The header, then one row per part.
    expect(rows[1]).toHaveTextContent("Resistors");
  });

  it("shows a stock column, batching the totals for the page into one query", async () => {
    respondWithSearch([resistor, microcontroller]);
    const { askedForTotals } = renderPartsPage();

    expect(await screen.findByRole("columnheader", { name: "Stock" })).toBeInTheDocument();
    const resistorRow = (await screen.findByRole("rowheader", { name: resistor.name })).closest(
      "tr",
    );
    expect(resistorRow).toHaveTextContent("42");
    // A part the totals route left out reads as zero, not an error.
    const microRow = screen.getByRole("rowheader", { name: microcontroller.name }).closest("tr");
    expect(microRow).toHaveTextContent("0");

    // One query carried both ids of the page, not one request per row (requirement 7.2).
    await expect.poll(() => askedForTotals.length).toBeGreaterThan(0);
    expect(askedForTotals.at(-1)).toEqual([resistor.id, microcontroller.id]);
  });

  it("narrows the list to what the search box asks for, after typing pauses", async () => {
    respondWithSearch([resistor, microcontroller]);
    renderPartsPage();
    await screen.findByRole("rowheader", { name: resistor.name });

    await userEvent
      .setup()
      .type(screen.getByRole("searchbox", { name: "Search by name or number" }), "ATmega");

    await expect.poll(partNames).toEqual(["ATmega328P"]);
  });

  it("keeps the search in the address so it can be shared", async () => {
    respondWithSearch([resistor, microcontroller]);
    const { router } = renderPartsPage();
    await screen.findByRole("rowheader", { name: resistor.name });

    await userEvent
      .setup()
      .type(screen.getByRole("searchbox", { name: "Search by name or number" }), "ATmega");

    await expect.poll(() => router.state.location.search).toMatchObject({ text: "ATmega" });
  });

  it("restores the search from the address on load", async () => {
    respondWithSearch([resistor, microcontroller]);
    renderPartsPage("/parts?text=ATmega");

    expect(await screen.findByRole("rowheader", { name: "ATmega328P" })).toBeInTheDocument();
    expect(screen.queryByRole("rowheader", { name: resistor.name })).not.toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search by name or number" })).toHaveValue(
      "ATmega",
    );
  });

  it("adds attribute columns and filters once a category is chosen", async () => {
    respondWithSearch([resistor]);
    renderPartsPage(`/parts?category=${resistors.id}`);

    expect(await screen.findByRole("rowheader", { name: resistor.name })).toBeInTheDocument();
    expect(await screen.findByRole("textbox", { name: "Resistance at least" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Resistance/ })).toBeInTheDocument();
  });

  it("narrows by the manufacturer, after typing pauses", async () => {
    respondWithSearch([resistor, microcontroller]);
    const { router } = renderPartsPage();
    await screen.findByRole("rowheader", { name: resistor.name });

    await userEvent.setup().type(screen.getByRole("textbox", { name: "Manufacturer" }), "micro");

    await expect.poll(partNames).toEqual(["ATmega328P"]);
    expect(router.state.location.search).toMatchObject({ manufacturer: "micro" });
  });

  it("asks the API for the parts in stock, keeping the choice in the address", async () => {
    const sent = respondWithSearch([resistor, microcontroller]);
    const { router } = renderPartsPage();
    await screen.findByRole("rowheader", { name: resistor.name });

    await userEvent
      .setup()
      .selectOptions(screen.getByRole("combobox", { name: "Stock" }), "In stock");

    await expect.poll(() => sent.at(-1)?.stock).toBe("in_stock");
    expect(router.state.location.search).toMatchObject({ stock: "in_stock" });
  });

  it("restores the stock filter from the address on load", async () => {
    const sent = respondWithSearch([resistor]);
    renderPartsPage("/parts?stock=out_of_stock");

    await screen.findByRole("rowheader", { name: resistor.name });
    expect(screen.getByRole("combobox", { name: "Stock" })).toHaveValue("out_of_stock");
    expect(sent.at(-1)?.stock).toBe("out_of_stock");
  });

  it("sorts by an attribute column when its header is clicked", async () => {
    const sent = respondWithSearch([resistor]);
    renderPartsPage(`/parts?category=${resistors.id}`);
    await screen.findByRole("rowheader", { name: resistor.name });

    await userEvent.setup().click(screen.getByRole("button", { name: /Sort by Resistance/ }));

    await expect.poll(() => sent.at(-1)?.sort).toBe("attribute:resistance");
  });

  it("shows the API's refusal next to the filter it named", async () => {
    respondWithSearch([]); // first load, before a bad bound
    renderPartsPage(`/parts?category=${resistors.id}`);
    await screen.findByRole("textbox", { name: "Resistance at least" });

    refuseSearch("filter resistance: the minimum is above the maximum");
    await userEvent
      .setup()
      .type(screen.getByRole("textbox", { name: "Resistance at least" }), "10k");

    expect(await screen.findByRole("alert")).toHaveTextContent("the minimum is above the maximum");
  });

  it("says when nothing matches and offers to clear the filters", async () => {
    respondWithSearch([resistor]);
    const { router } = renderPartsPage();
    await screen.findByRole("rowheader", { name: resistor.name });

    await userEvent
      .setup()
      .type(screen.getByRole("searchbox", { name: "Search by name or number" }), "diode");

    expect(await screen.findByText(/No part matches/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Clear filters" }));

    await expect.poll(() => router.state.location.search).toEqual({});
    expect(await screen.findByRole("rowheader", { name: resistor.name })).toBeInTheDocument();
  });

  it("invites the owner to start when the catalog is empty", async () => {
    respondWithSearch([]);
    renderPartsPage();

    expect(await screen.findByText(/No parts yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear filters" })).not.toBeInTheDocument();
  });

  describe("in pages", () => {
    // 120 parts, so a list of 50 has three pages and a list of 25 has five.
    const many = Array.from({ length: 120 }, (_, index) =>
      aSearchResult({
        id: `0199cccc-0000-7000-8000-0000000${String(index).padStart(5, "0")}`,
        name: `Resistor ${String(index).padStart(3, "0")}`,
        category_id: passives.id,
      }),
    );

    function pages() {
      return screen.getByRole("navigation", { name: "Pages of the parts list" });
    }

    /** Waits for the bar to say which rows are on screen. */
    async function showing(range: string) {
      const bar = await screen.findByRole("navigation", { name: "Pages of the parts list" });
      return within(bar).findByText(range);
    }

    it("shows 50 at a time and says how many there are", async () => {
      const sent = respondWithSearch(many);
      renderPartsPage();

      expect(await showing("1–50 of 120")).toBeInTheDocument();
      expect(partNames()).toHaveLength(50);
      expect(within(pages()).getByRole("button", { name: "Page 1" })).toHaveAttribute(
        "aria-current",
        "page",
      );
      expect(sent.at(-1)).toMatchObject({ page: 1, page_size: 50 });
      expect(sent.at(-1)).not.toHaveProperty("limit");
      expect(sent.at(-1)).not.toHaveProperty("cursor");
    });

    it("asks for the next page, puts it in the address, and Back returns", async () => {
      const sent = respondWithSearch(many);
      const { router } = renderPartsPage();
      await showing("1–50 of 120");

      await userEvent.setup().click(within(pages()).getByRole("button", { name: "Next page" }));

      await waitFor(() => expect(router.state.location.search).toEqual({ page: 2 }));
      expect(await showing("51–100 of 120")).toBeInTheDocument();
      expect(sent.at(-1)).toMatchObject({ page: 2, page_size: 50 });
      expect(partNames()[0]).toBe("Resistor 050");

      router.history.back();

      await waitFor(() => expect(router.state.location.search).toEqual({}));
      expect(await showing("1–50 of 120")).toBeInTheDocument();
      expect(partNames()[0]).toBe("Resistor 000");
    });

    it("starts again at page 1 for a new sort, at the size chosen", async () => {
      const sent = respondWithSearch(many);
      const { router } = renderPartsPage("/parts?page=2&size=25");
      await showing("26–50 of 120");

      await userEvent.setup().click(screen.getByRole("button", { name: /^Sort by name/ }));

      await waitFor(() => expect(router.state.location.search).toEqual({ sort: "name", size: 25 }));
      await expect.poll(() => sent.at(-1)).toMatchObject({ sort: "name", page: 1, page_size: 25 });
    });

    it("starts again at page 1 for a typed filter, at the size chosen", async () => {
      respondWithSearch(many);
      const { router } = renderPartsPage("/parts?page=3&size=25");
      await showing("51–75 of 120");

      await userEvent
        .setup()
        .type(screen.getByRole("searchbox", { name: "Search by name or number" }), "Resistor 1");

      await waitFor(() =>
        expect(router.state.location.search).toEqual({ text: "Resistor 1", size: 25 }),
      );
      expect(await showing("1–20 of 20")).toBeInTheDocument();
    });

    it("opens the last page when the address asks for one past the end", async () => {
      respondWithSearch(many);
      const { router } = renderPartsPage("/parts?page=9");

      expect(await showing("101–120 of 120")).toBeInTheDocument();
      await waitFor(() => expect(router.state.location.search).toEqual({ page: 3 }));
      expect(partNames()).toHaveLength(20);
    });
  });

  it("offers to import from a sheet beside New part", async () => {
    respondWithSearch([resistor]);
    const { router } = renderPartsPage();

    expect(await screen.findByRole("link", { name: "New part" })).toBeVisible();
    await userEvent.setup().click(screen.getByRole("link", { name: "Import from a sheet" }));

    await expect.poll(() => router.state.location.pathname).toBe("/import");
    expect(await screen.findByRole("heading", { name: "Import from a sheet" })).toBeVisible();
  });

  it("says so when the parts can't be loaded", async () => {
    renderPartsPage();
    server.use(http.post("*/api/catalog/parts/search", () => HttpResponse.error()));

    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't be loaded");
  });
});
