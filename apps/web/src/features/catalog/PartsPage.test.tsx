import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen } from "@testing-library/react";
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
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: [initial] });
  const router = createAppRouter(queryClient, history);
  renderWithProviders(<RouterProvider router={router} />, { queryClient });
  return router;
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
    const router = renderPartsPage();
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
    const router = renderPartsPage();
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

  it("shows the next page when asked for more", async () => {
    const many = Array.from({ length: 51 }, (_, index) =>
      aSearchResult({
        id: `0199cccc-0000-7000-8000-0000000${String(index).padStart(5, "0")}`,
        name: `Resistor ${index}`,
        category_id: passives.id,
      }),
    );
    respondWithSearch(many);
    renderPartsPage();
    await screen.findByRole("rowheader", { name: "Resistor 0" });

    expect(partNames()).toHaveLength(50);
    await userEvent.setup().click(screen.getByRole("button", { name: "Show more parts" }));

    await expect.poll(() => partNames().length).toBe(51);
    expect(screen.queryByRole("button", { name: "Show more parts" })).not.toBeInTheDocument();
  });

  it("says so when the parts can't be loaded", async () => {
    renderPartsPage();
    server.use(http.post("*/api/catalog/parts/search", () => HttpResponse.error()));

    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't be loaded");
  });
});
