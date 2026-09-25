import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aCategory,
  aPart,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithCategories,
  respondWithParts,
  server,
} from "../../test/server";

const passives = aCategory({ name: "Passives", part_count: 1 });
const semiconductors = aCategory({
  id: "0199bbbb-0000-7000-8000-000000000002",
  name: "Semiconductors",
  part_count: 1,
});

const resistor = aPart({ name: "4.7 kΩ 1% 0805", category_id: passives.id });
const microcontroller = aPart({
  id: "0199cccc-0000-7000-8000-000000000002",
  name: "ATmega328P",
  category_id: semiconductors.id,
  manufacturer: "Microchip",
  mpn: "ATMEGA328P-PU",
  package: "DIP-28",
});

function renderPartsPage() {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: ["/parts"] });
  renderWithProviders(<RouterProvider router={createAppRouter(queryClient, history)} />, {
    queryClient,
  });
}

function partNames(): string[] {
  return screen.queryAllByRole("rowheader").map((cell) => cell.textContent ?? "");
}

describe("PartsPage", () => {
  it("lists every part with its category", async () => {
    respondWithCategories([passives, semiconductors]);
    respondWithParts([resistor, microcontroller]);
    renderPartsPage();

    expect(await screen.findByRole("rowheader", { name: resistor.name })).toBeInTheDocument();

    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(3); // The header, then one row per part.
    expect(rows[1]).toHaveTextContent("Passives");
    expect(rows[2]).toHaveTextContent("Semiconductors");
    expect(rows[2]).toHaveTextContent("ATMEGA328P-PU");
  });

  it("narrows the list to what the search box asks for", async () => {
    respondWithCategories([passives, semiconductors]);
    respondWithParts([resistor, microcontroller]);
    renderPartsPage();
    await screen.findByRole("rowheader", { name: resistor.name });

    await userEvent
      .setup()
      .type(screen.getByRole("searchbox", { name: "Search by name" }), "ATmega");

    await expect.poll(partNames).toEqual(["ATmega328P"]);
  });

  it("narrows the list to one category", async () => {
    respondWithCategories([passives, semiconductors]);
    respondWithParts([resistor, microcontroller]);
    renderPartsPage();
    await screen.findByRole("rowheader", { name: resistor.name });

    const filter = screen.getByRole("combobox", { name: "Category" });
    await userEvent.setup().selectOptions(filter, screen.getByRole("option", { name: "Passives" }));

    await expect.poll(partNames).toEqual([resistor.name]);
  });

  it("says when nothing matches the search, without offering to load more", async () => {
    respondWithCategories([passives]);
    respondWithParts([resistor]);
    renderPartsPage();
    await screen.findByRole("rowheader", { name: resistor.name });

    await userEvent
      .setup()
      .type(screen.getByRole("searchbox", { name: "Search by name" }), "diode");

    expect(await screen.findByText(/No part matches/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("invites the owner to start when the catalog is empty", async () => {
    respondWithCategories([]);
    respondWithParts([]);
    renderPartsPage();

    expect(await screen.findByText(/No parts yet/)).toBeInTheDocument();
  });

  it("shows the next page when asked for more", async () => {
    const many = Array.from({ length: 51 }, (_, index) =>
      aPart({
        id: `0199cccc-0000-7000-8000-0000000${String(index).padStart(5, "0")}`,
        name: `Resistor ${index}`,
        category_id: passives.id,
      }),
    );
    respondWithCategories([passives]);
    respondWithParts(many);
    renderPartsPage();
    await screen.findByRole("rowheader", { name: "Resistor 0" });

    expect(partNames()).toHaveLength(50);
    await userEvent.setup().click(screen.getByRole("button", { name: "Show more parts" }));

    await expect.poll(() => partNames().length).toBe(51);
    expect(screen.queryByRole("button", { name: "Show more parts" })).not.toBeInTheDocument();
  });

  it("says so when the parts can't be loaded", async () => {
    respondWithCategories([passives]);
    renderPartsPage();
    server.use(http.get("*/api/catalog/parts", () => HttpResponse.error()));

    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't be loaded");
  });
});
