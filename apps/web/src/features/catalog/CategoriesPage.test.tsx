import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aCategory,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithCategories,
} from "../../test/server";

const passives = aCategory({ name: "Passives", child_count: 1 });
const resistors = aCategory({
  id: "0199bbbb-0000-7000-8000-000000000002",
  parent_id: passives.id,
  name: "Resistors",
  part_count: 3,
});

function renderCategoriesPage() {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: ["/categories"] });
  renderWithProviders(<RouterProvider router={createAppRouter(queryClient, history)} />, {
    queryClient,
  });
}

describe("CategoriesPage", () => {
  it("shows the tree, each category with what hangs off it", async () => {
    respondWithCategories([passives, resistors]);
    renderCategoriesPage();

    const tree = await screen.findByRole("list", { name: "Category tree" });
    const items = within(tree).getAllByRole("listitem");

    expect(items).toHaveLength(2);
    const parent = items[0] as HTMLElement;
    const child = items[1] as HTMLElement;
    expect(parent).toHaveTextContent("Passives");
    expect(parent).toHaveTextContent("Subcategories: 1");
    expect(child).toHaveTextContent("Resistors");
    expect(child).toHaveTextContent("Parts: 3");
    // The child hangs off its parent rather than sitting beside it.
    expect(parent).toContainElement(child);
  });

  it("says when there are no categories yet", async () => {
    respondWithCategories([]);
    renderCategoriesPage();

    expect(await screen.findByText(/No categories yet/)).toBeInTheDocument();
  });
});
