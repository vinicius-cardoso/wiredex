import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../../test/render";
import { aCategory, anAttribute, aSearchResult } from "../../../test/server";
import { ResultsTable } from "./ResultsTable";
import type { SortField } from "./searchParams";

/** A router with the part route the table links to, so `<Link>` resolves in the test. */
function renderInPartsRouter(ui: ReactElement) {
  const rootRoute = createRootRoute({ component: Outlet });
  const home = createRoute({ getParentRoute: () => rootRoute, path: "/", component: () => ui });
  const part = createRoute({
    getParentRoute: () => rootRoute,
    path: "/parts/$partId",
    component: () => null,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([home, part]),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  return renderWithProviders(<RouterProvider router={router} />);
}

const resistors = aCategory({ name: "Resistors" });
const resistance = anAttribute({
  key: "resistance",
  label: "Resistance",
  kind: "number",
  unit: "Ω",
});
const tolerance = anAttribute({
  id: "0199dddd-0000-7000-8000-00000000000b",
  key: "tolerance",
  label: "Tolerance",
  kind: "enum",
  unit: null,
  options: ["1%", "5%"],
});

const part = aSearchResult({
  name: "4.7 kΩ 1% 0805",
  category_id: resistors.id,
  mpn: "RC0805",
  attributes: {
    resistance: { value: "4700", display: "4.7k", unit: "Ω" },
    tolerance: { value: "1%", display: "1%", unit: null },
  },
});

function render(sort: SortField = "newest", onSort = vi.fn()) {
  return renderInPartsRouter(
    <ResultsTable
      results={[part]}
      categories={[resistors]}
      attributes={[resistance, tolerance]}
      sort={sort}
      direction="desc"
      onSort={onSort}
    />,
  );
}

describe("ResultsTable", () => {
  it("shows a column per number and enum attribute, with the value and unit", async () => {
    render();

    expect(await screen.findByRole("columnheader", { name: /Resistance/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Tolerance" })).toBeInTheDocument();

    const row = screen.getByRole("rowheader", { name: "4.7 kΩ 1% 0805" }).closest("tr");
    expect(within(row as HTMLElement).getByText("4.7kΩ")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("Resistors")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("RC0805")).toBeInTheDocument();
  });

  it("marks the sorted column with aria-sort", async () => {
    render({ attribute: "resistance" });

    const header = await screen.findByRole("columnheader", { name: /Resistance/ });
    expect(header).toHaveAttribute("aria-sort", "descending");
    // The name header, not the active one, reads as unsorted.
    expect(screen.getByRole("columnheader", { name: /Name/ })).toHaveAttribute("aria-sort", "none");
  });

  it("asks to sort by an attribute when its header is clicked", async () => {
    const onSort = vi.fn();
    render("newest", onSort);

    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: /Sort by Resistance/ }));

    expect(onSort).toHaveBeenCalledWith({ attribute: "resistance" });
  });

  it("does not make an enum column sortable", async () => {
    render();

    // The name and number headers are buttons; the enum column is a plain header.
    await screen.findByRole("button", { name: /Sort by Resistance/ });
    expect(screen.queryByRole("button", { name: /Sort by Tolerance/ })).not.toBeInTheDocument();
  });
});
