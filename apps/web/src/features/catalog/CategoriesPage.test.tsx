import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aCategory,
  acceptCategoryDeletion,
  acceptCategoryEdits,
  acceptNewCategories,
  anAttribute,
  refuseCategoryDeletion,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithCategories,
  respondWithCategorySchema,
} from "../../test/server";

const passives = aCategory({ name: "Passives", child_count: 1 });
const resistors = aCategory({
  id: "0199bbbb-0000-7000-8000-000000000002",
  parent_id: passives.id,
  name: "Resistors",
  part_count: 3,
});
const semiconductors = aCategory({
  id: "0199bbbb-0000-7000-8000-000000000003",
  name: "Semiconductors",
});

const resistance = anAttribute({ category_id: resistors.id, label: "Resistance" });
const rohs = anAttribute({
  id: "0199dddd-0000-7000-8000-00000000000a",
  category_id: passives.id,
  key: "rohs",
  label: "RoHS",
  kind: "bool",
  unit: null,
  required: false,
  inherited: true,
});

function renderCategoriesPage(categories = [passives, resistors, semiconductors]) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  respondWithCategories(categories);
  respondWithCategorySchema(resistors, [rohs, resistance]);
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: ["/categories"] });
  renderWithProviders(<RouterProvider router={createAppRouter(queryClient, history)} />, {
    queryClient,
  });
}

/** Tabs until the tree takes focus: how many stops lie before it is the layout's business. */
async function tabInto(user: ReturnType<typeof userEvent.setup>, tree: HTMLElement) {
  for (let stop = 0; stop < 20; stop += 1) {
    await user.tab();
    if (tree.contains(document.activeElement)) return;
  }
  throw new Error("the tree never took focus");
}

describe("CategoriesPage", () => {
  it("shows the tree, each category with what hangs off it", async () => {
    renderCategoriesPage();

    const tree = await screen.findByRole("tree", { name: "Category tree" });
    const items = within(tree).getAllByRole("treeitem");

    expect(items.map((item) => item.getAttribute("aria-label"))).toEqual([
      "Passives",
      "Resistors",
      "Semiconductors",
    ]);
    expect(items[1]).toHaveAttribute("aria-level", "2");
    expect(items[1]).toHaveTextContent("Parts: 3");
  });

  it("is walked and picked with the keyboard alone", async () => {
    renderCategoriesPage();
    const user = userEvent.setup();
    const tree = await screen.findByRole("tree", { name: "Category tree" });

    await tabInto(user, tree);
    expect(screen.getByRole("treeitem", { name: "Passives" })).toHaveFocus();

    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("treeitem", { name: "Resistors" })).toHaveFocus();

    await user.keyboard("{Enter}");
    expect(screen.getByRole("treeitem", { name: "Resistors" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(await screen.findByRole("heading", { level: 2, name: "Resistors" })).toBeInTheDocument();

    // Left folds the branch away, so its child leaves the tree.
    await user.keyboard("{ArrowUp}{ArrowLeft}");
    expect(within(tree).getAllByRole("treeitem")).toHaveLength(2);
    expect(screen.getByRole("treeitem", { name: "Passives" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );

    await user.keyboard("{ArrowRight}{End}");
    expect(screen.getByRole("treeitem", { name: "Semiconductors" })).toHaveFocus();
  });

  it("adds a category inside the selected one", async () => {
    renderCategoriesPage();
    const sent = acceptNewCategories();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("treeitem", { name: "Passives" }));
    await user.type(screen.getByRole("textbox", { name: "Add a category" }), "Capacitors");
    await user.click(screen.getByRole("button", { name: "Add" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ name: "Capacitors", parent_id: passives.id });
  });

  it("renames and moves the selected category", async () => {
    renderCategoriesPage();
    const sent = acceptCategoryEdits();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("treeitem", { name: "Resistors" }));
    const nameBox = screen.getByRole("textbox", { name: "Name" });
    await user.clear(nameBox);
    await user.type(nameBox, "Fixed resistors");
    await user.click(screen.getByRole("button", { name: "Rename" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ name: "Fixed resistors" });

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Inside" }),
      screen.getByRole("option", { name: "Semiconductors" }),
    );

    await expect.poll(() => sent.length).toBe(2);
    expect(sent[1]).toEqual({ parent_id: semiconductors.id });
  });

  it("says why a category in use can't be deleted, without leaving the page", async () => {
    renderCategoriesPage();
    refuseCategoryDeletion("Resistors still holds 3 parts");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("treeitem", { name: "Resistors" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete category" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("still holds 3 parts");
    expect(screen.getByRole("tree", { name: "Category tree" })).toBeInTheDocument();
  });

  it("deletes an empty category and lets the panel go", async () => {
    renderCategoriesPage();
    acceptCategoryDeletion();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("treeitem", { name: "Semiconductors" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete category" }));

    await expect
      .poll(() => screen.queryByRole("heading", { level: 2, name: "Semiconductors" }))
      .toBeNull();
  });

  it("says when there are no categories yet", async () => {
    renderCategoriesPage([]);

    expect(await screen.findByText(/No categories yet/)).toBeInTheDocument();
  });
});
