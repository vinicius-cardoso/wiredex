import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aReorderLine,
  aReorderList,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithReorder,
  server,
} from "../../test/server";

function renderAt(path: string) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: [path] });
  renderWithProviders(<RouterProvider router={createAppRouter(queryClient, history)} />, {
    queryClient,
  });
}

const insert = aReorderLine();
const esp = aReorderLine({
  part_id: "0199cccc-0000-7000-8000-0000000000e2",
  name: "ESP32-C3 Super Mini",
  mpn: "ESP32-C3",
  category: { id: "0199cccc-0000-7000-8000-0000000000c2", name: "Boards" },
  minimum: 2,
  minimum_from: { id: "0199cccc-0000-7000-8000-0000000000c3", name: "Modules" },
  have: 0,
  missing: 2,
});

describe("ReorderPage", () => {
  it("lists each part below its minimum with what there is and what is missing", async () => {
    respondWithReorder(aReorderList({ items: [esp, insert] }));
    renderAt("/reorder");

    const table = await screen.findByRole("table", { name: "Parts below their minimum stock" });
    const [, first, second] = within(table).getAllByRole("row");
    expect(first).toHaveTextContent("ESP32-C3 Super MiniESP32-C3Boards02from Modules2");
    expect(second).toHaveTextContent("M3 heat-set insertInserts405010");
    expect(within(table).getByRole("link", { name: "M3 heat-set insert" })).toHaveAttribute(
      "href",
      `/parts/${insert.part_id}`,
    );
    expect(screen.getByText("2 parts to reorder")).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Free" })).toBeInTheDocument();
  });

  it("says what the minimums were compared against, and where to change it", async () => {
    respondWithReorder(aReorderList({ basis: "total", items: [insert] }));
    renderAt("/reorder");

    expect(
      await screen.findByText(
        /Compared against total stock: everything on hand, reserved or not\./,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Change this in Settings" })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(screen.getByRole("columnheader", { name: "On hand" })).toBeInTheDocument();
  });

  it("says how to start when nothing is listed", async () => {
    respondWithReorder(aReorderList());
    renderAt("/reorder");

    expect(await screen.findByText(/Nothing to reorder/)).toHaveTextContent(
      "A part with no minimum is never listed here.",
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("says so when the list can't be read", async () => {
    server.use(http.get("*/api/catalog/reorder", () => HttpResponse.json({}, { status: 500 })));
    renderAt("/reorder");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The reorder list couldn't be loaded.",
    );
  });

  it("is in the navigation", async () => {
    respondWithReorder(aReorderList());
    renderAt("/reorder");

    const nav = await screen.findByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getByRole("link", { name: "Reorder" })).toHaveAttribute("href", "/reorder");
  });
});
