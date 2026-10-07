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
  aSearchResult,
  refuseCategoryDeletion,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithCategories,
  respondWithCategorySchema,
  respondWithPartTotals,
  respondWithSearch,
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
  // The picked category's parts: none unless a test says otherwise.
  respondWithSearch([]);
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: ["/categories"] });
  const router = createAppRouter(queryClient, history);
  renderWithProviders(<RouterProvider router={router} />, { queryClient });
  return { router };
}

/** Tabs until the tree takes focus: how many stops lie before it is the layout's business. */
async function tabInto(user: ReturnType<typeof userEvent.setup>, tree: HTMLElement) {
  for (let stop = 0; stop < 40; stop += 1) {
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
    // One line each: the name, then a quiet count of its parts.
    expect(within(items[1] as HTMLElement).getByTitle("3 parts")).toHaveTextContent("3");
  });

  it("narrows the tree by name, keeping the ancestors of a match in view", async () => {
    renderCategoriesPage();
    const user = userEvent.setup();

    await user.type(await screen.findByRole("searchbox", { name: "Filter categories" }), "resis");

    const tree = screen.getByRole("tree", { name: "Category tree" });
    expect(
      within(tree)
        .getAllByRole("treeitem")
        .map((item) => item.getAttribute("aria-label")),
    ).toEqual(["Passives", "Resistors"]);

    await user.clear(screen.getByRole("searchbox", { name: "Filter categories" }));
    await user.type(screen.getByRole("searchbox", { name: "Filter categories" }), "nothing");
    expect(screen.getByText("No category matches that.")).toHaveAttribute("role", "status");
    expect(screen.queryByRole("tree")).toBeNull();
  });

  it("offers to clear the filter while it narrows the tree", async () => {
    renderCategoriesPage();
    const user = userEvent.setup();
    const filter = await screen.findByRole("searchbox", { name: "Filter categories" });
    expect(screen.queryByRole("button", { name: "Clear" })).toBeNull();

    await user.type(filter, "nothing");
    await user.click(screen.getByRole("button", { name: "Clear" }));

    expect(filter).toHaveValue("");
    expect(screen.getByRole("tree", { name: "Category tree" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear" })).toBeNull();
  });

  it("folds a branch from its chevron without picking it", async () => {
    renderCategoriesPage();
    const user = userEvent.setup();
    const passivesItem = await screen.findByRole("treeitem", { name: "Passives" });

    const chevron = passivesItem.querySelector("[aria-hidden='true']");
    await user.click(chevron as Element);

    expect(passivesItem).toHaveAttribute("aria-expanded", "false");
    expect(passivesItem).toHaveAttribute("aria-selected", "false");
    expect(screen.queryByRole("treeitem", { name: "Resistors" })).toBeNull();
  });

  it("adds a category at the top level while none is picked", async () => {
    renderCategoriesPage();
    const sent = acceptNewCategories();
    const user = userEvent.setup();

    const box = await screen.findByRole("textbox", { name: "Add a category" });
    expect(box).toHaveAccessibleDescription("It will sit at the top level.");
    await user.type(box, "Sensors{Enter}");

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ name: "Sensors", parent_id: null });
  });

  it("lists the parts filed in the picked category, each with its number and stock", async () => {
    renderCategoriesPage();
    // After the page's own default, so these answer the search the pick makes.
    const sent = respondWithSearch([
      aSearchResult({
        id: "0199cccc-0000-7000-8000-0000000000e1",
        category_id: resistors.id,
        name: "R 4k7 0805",
        mpn: "RC0805FR-074K7L",
      }),
    ]);
    respondWithPartTotals([{ part_id: "0199cccc-0000-7000-8000-0000000000e1", on_hand: 120 }]);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("treeitem", { name: "Resistors" }));

    const parts = await screen.findByRole("region", { name: "Parts in Resistors" });
    const row = await within(parts).findByRole("row", { name: /R 4k7 0805/ });
    expect(within(row).getByRole("link", { name: "R 4k7 0805" })).toHaveAttribute(
      "href",
      "/parts/0199cccc-0000-7000-8000-0000000000e1",
    );
    expect(row).toHaveTextContent("RC0805FR-074K7L");
    expect(await within(row).findByText("120")).toBeVisible();
    // Only what is filed in the category itself, as its count says.
    expect(sent.at(-1)).toMatchObject({ category_id: resistors.id, exact_category: true });
    expect(within(parts).getByRole("link", { name: "Open in Parts" })).toHaveAttribute(
      "href",
      `/parts?category=${resistors.id}&exact=true`,
    );
  });

  it("pages the picked category's parts in place, and another category starts at page 1", async () => {
    const { router } = renderCategoriesPage();
    const filed = (category: string, count: number, prefix: string) =>
      Array.from({ length: count }, (_, index) =>
        aSearchResult({
          id: `0199cccc-0000-7000-8000-${prefix}${String(index).padStart(4, "0")}`,
          category_id: category,
          name: `${prefix} ${String(index).padStart(3, "0")}`,
        }),
      );
    const sent = respondWithSearch([
      ...filed(resistors.id, 60, "00000001"),
      ...filed(passives.id, 55, "00000002"),
    ]);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("treeitem", { name: "Resistors" }));
    const bar = await screen.findByRole("navigation", { name: "Pages of this category's parts" });
    expect(await within(bar).findByText("1–50 of 60")).toBeVisible();

    await user.click(within(bar).getByRole("button", { name: "Next page" }));

    expect(await within(bar).findByText("51–60 of 60")).toBeVisible();
    expect(sent.at(-1)).toMatchObject({ category_id: resistors.id, page: 2, page_size: 50 });
    // The panel's page is its own: the address doesn't change.
    expect(router.state.location.search).toEqual({});

    await user.click(screen.getByRole("treeitem", { name: "Passives" }));

    const other = await screen.findByRole("navigation", {
      name: "Pages of this category's parts",
    });
    expect(await within(other).findByText("1–50 of 55")).toBeVisible();
    expect(sent.at(-1)).toMatchObject({ category_id: passives.id, page: 1 });
  });

  it("says when no part is filed in the picked category", async () => {
    renderCategoriesPage();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("treeitem", { name: "Semiconductors" }));

    const parts = await screen.findByRole("region", { name: "Parts in Semiconductors" });
    expect(await within(parts).findByText("No part is filed in this category.")).toBeVisible();
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

  it("adds a category at the top level with one picked, when asked to", async () => {
    renderCategoriesPage();
    const sent = acceptNewCategories();
    const user = userEvent.setup();
    const box = await screen.findByRole("textbox", { name: "Add a category" });
    // Nothing picked: the top level is the only place, so there is nothing to choose.
    expect(screen.queryByRole("combobox", { name: "Where it goes" })).toBeNull();

    await user.click(await screen.findByRole("treeitem", { name: "Passives" }));
    const where = screen.getByRole("combobox", { name: "Where it goes" });
    expect(where).toHaveDisplayValue("Inside Passives");
    await user.selectOptions(where, "At the top level");
    expect(box).toHaveAccessibleDescription("It will sit at the top level.");
    expect(box).toHaveAttribute("placeholder", "New category at the top level");
    await user.type(box, "Mechanical");
    await user.click(screen.getByRole("button", { name: "Add" }));
    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ name: "Mechanical", parent_id: null });

    // Another pick is where the next one goes again.
    await user.click(screen.getByRole("treeitem", { name: "Semiconductors" }));
    expect(screen.getByRole("combobox", { name: "Where it goes" })).toHaveDisplayValue(
      "Inside Semiconductors",
    );
    expect(box).toHaveAccessibleDescription("It will sit inside Semiconductors.");
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

  it("shows the resolved tracking answer when the category inherits it", async () => {
    // Resistors leaves the flag unset and inherits a "yes" from above.
    const inheriting = aCategory({
      id: resistors.id,
      parent_id: passives.id,
      name: "Resistors",
      tracked_individually: null,
      tracked_individually_resolved: true,
    });
    renderCategoriesPage([passives, inheriting, semiconductors]);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("treeitem", { name: "Resistors" }));
    const control = screen.getByRole("combobox", { name: "Tracked individually" });
    expect(control).toHaveValue("inherit");
    expect(screen.getByText(/Inherited: yes/)).toBeInTheDocument();
  });

  it("sets the tracking flag from the tri-state control", async () => {
    renderCategoriesPage();
    const sent = acceptCategoryEdits();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("treeitem", { name: "Resistors" }));
    const control = screen.getByRole("combobox", { name: "Tracked individually" });
    await user.selectOptions(control, within(control).getByRole("option", { name: "Yes" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ tracked_individually: true });
  });

  it("offers the not-stocked flag as inherit, yes or no, beside tracking", async () => {
    // 09's requirement 11.10: Resistors sets it; the control shows what is set.
    const consumable = aCategory({
      id: resistors.id,
      parent_id: passives.id,
      name: "Resistors",
      not_stocked: true,
      not_stocked_resolved: true,
    });
    renderCategoriesPage([passives, consumable, semiconductors]);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("treeitem", { name: "Resistors" }));
    const control = screen.getByRole("combobox", { name: "Not stocked" });

    expect(control).toHaveValue("yes");
    expect(
      within(control)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Inherit from the parent", "Yes", "No"]);
    // Set here, so nothing is inherited to explain.
    expect(screen.queryByText(/parts here are consumables/)).not.toBeInTheDocument();
  });

  it("shows the resolved not-stocked answer while the category inherits it", async () => {
    const inheriting = aCategory({
      id: resistors.id,
      parent_id: passives.id,
      name: "Resistors",
      not_stocked: null,
      not_stocked_resolved: true,
    });
    renderCategoriesPage([passives, inheriting, semiconductors]);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("treeitem", { name: "Resistors" }));

    expect(screen.getByRole("combobox", { name: "Not stocked" })).toHaveValue("inherit");
    expect(screen.getByText(/Inherited: yes, parts here are consumables/)).toBeInTheDocument();
    // Tracking inherits a no on its own: the two flags resolve independently.
    expect(screen.getByText(/Inherited: no, parts here are counted in lots/)).toBeInTheDocument();
  });

  it.each([
    ["Yes", true],
    ["No", false],
    ["Inherit from the parent", null],
  ])("sends %s as not_stocked %s", async (option, sentValue) => {
    const set = aCategory({
      id: resistors.id,
      parent_id: passives.id,
      name: "Resistors",
      // Something other than each option, so every choice is a change the select reports.
      not_stocked: sentValue === null ? true : !sentValue,
    });
    renderCategoriesPage([passives, set, semiconductors]);
    const sent = acceptCategoryEdits();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("treeitem", { name: "Resistors" }));
    const control = screen.getByRole("combobox", { name: "Not stocked" });
    await user.selectOptions(control, within(control).getByRole("option", { name: option }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ not_stocked: sentValue });
  });
});
