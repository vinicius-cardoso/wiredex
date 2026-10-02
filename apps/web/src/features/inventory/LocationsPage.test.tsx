import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  acceptLocationDeletion,
  acceptLocationEdits,
  acceptNewLocations,
  aLocation,
  refuseLocationDeletion,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithLocations,
} from "../../test/server";

const lab = aLocation({ name: "Lab", code: "WX-L-0001", child_count: 1 });
const drawer = aLocation({
  id: "0199ffff-0000-7000-8000-000000000002",
  parent_id: lab.id,
  name: "Drawer 3",
  code: "WX-L-0002",
  lot_count: 5,
});
const box = aLocation({
  id: "0199ffff-0000-7000-8000-000000000003",
  name: "Parts box",
  code: "WX-L-0003",
});

function renderLocationsPage(locations = [lab, drawer, box], path = "/locations") {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  respondWithLocations(locations);
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: [path] });
  renderWithProviders(<RouterProvider router={createAppRouter(queryClient, history)} />, {
    queryClient,
  });
}

/** Tabs until the tree takes focus: how many stops lie before it is the layout's business. */
async function tabInto(user: ReturnType<typeof userEvent.setup>, tree: HTMLElement) {
  for (let stop = 0; stop < 40; stop += 1) {
    await user.tab();
    if (tree.contains(document.activeElement)) return;
  }
  throw new Error("the tree never took focus");
}

describe("LocationsPage", () => {
  it("shows the tree, each location with its code and what it holds", async () => {
    renderLocationsPage();

    const tree = await screen.findByRole("tree", { name: "Location tree" });
    const items = within(tree).getAllByRole("treeitem");

    expect(items.map((item) => item.getAttribute("aria-label"))).toEqual([
      "Lab",
      "Drawer 3",
      "Parts box",
    ]);
    expect(items[1]).toHaveAttribute("aria-level", "2");
    expect(items[1]).toHaveTextContent("WX-L-0002");
    expect(items[1]).toHaveTextContent("Lots: 5");
  });

  it("is walked and picked with the keyboard alone", async () => {
    renderLocationsPage();
    const user = userEvent.setup();
    const tree = await screen.findByRole("tree", { name: "Location tree" });

    await tabInto(user, tree);
    expect(screen.getByRole("treeitem", { name: "Lab" })).toHaveFocus();

    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("treeitem", { name: "Drawer 3" })).toHaveFocus();

    await user.keyboard("{Enter}");
    expect(screen.getByRole("treeitem", { name: "Drawer 3" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(await screen.findByRole("heading", { level: 2, name: /Drawer 3/ })).toBeInTheDocument();

    // Left folds the branch away, so its child leaves the tree.
    await user.keyboard("{ArrowUp}{ArrowLeft}");
    expect(within(tree).getAllByRole("treeitem")).toHaveLength(2);
    expect(screen.getByRole("treeitem", { name: "Lab" })).toHaveAttribute("aria-expanded", "false");

    await user.keyboard("{ArrowRight}{End}");
    expect(screen.getByRole("treeitem", { name: "Parts box" })).toHaveFocus();
  });

  it("opens with the location its address names selected", async () => {
    // 19-command-palette, requirement 5.4: the palette sends a found location here.
    renderLocationsPage([lab, drawer, box], `/locations?selected=${drawer.id}`);

    expect(await screen.findByRole("heading", { level: 2, name: /Drawer 3/ })).toBeVisible();
    expect(screen.getByRole("treeitem", { name: "Drawer 3" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("adds a location inside the selected one", async () => {
    renderLocationsPage();
    const sent = acceptNewLocations();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("treeitem", { name: "Lab" }));
    await user.type(screen.getByRole("textbox", { name: "Add a location" }), "Shelf A");
    await user.click(screen.getByRole("button", { name: "Add" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ name: "Shelf A", parent_id: lab.id });
  });

  it("renames and moves the selected location", async () => {
    renderLocationsPage();
    const sent = acceptLocationEdits();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("treeitem", { name: "Drawer 3" }));
    const nameBox = screen.getByRole("textbox", { name: "Name" });
    await user.clear(nameBox);
    await user.type(nameBox, "Drawer three");
    await user.click(screen.getByRole("button", { name: "Rename" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ name: "Drawer three" });

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Inside" }),
      screen.getByRole("option", { name: /Parts box/ }),
    );

    await expect.poll(() => sent.length).toBe(2);
    expect(sent[1]).toEqual({ parent_id: box.id });
  });

  it("says why a location in use can't be deleted, without leaving the page", async () => {
    renderLocationsPage();
    refuseLocationDeletion("Drawer 3 still holds 5 lots");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("treeitem", { name: "Drawer 3" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete location" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("still holds 5 lots");
    expect(screen.getByRole("tree", { name: "Location tree" })).toBeInTheDocument();
  });

  it("deletes an empty location and lets the panel go", async () => {
    renderLocationsPage();
    acceptLocationDeletion();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("treeitem", { name: "Parts box" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete location" }));

    await expect
      .poll(() => screen.queryByRole("heading", { level: 2, name: /Parts box/ }))
      .toBeNull();
  });

  it("says when there are no locations yet", async () => {
    renderLocationsPage([]);

    expect(await screen.findByText(/No locations yet/)).toBeInTheDocument();
    expect(screen.queryByRole("searchbox", { name: "Filter locations" })).toBeNull();
  });

  it("filters by name, keeping each match's ancestors in the tree", async () => {
    renderLocationsPage();
    const user = userEvent.setup();
    await screen.findByRole("tree", { name: "Location tree" });

    await user.type(screen.getByRole("searchbox", { name: "Filter locations" }), "DRAWER");

    expect(namesIn(screen.getByRole("tree", { name: "Location tree" }))).toEqual([
      "Lab",
      "Drawer 3",
    ]);
  });

  it("filters by name, not by path: a parent's name keeps only the parent", async () => {
    renderLocationsPage();
    const user = userEvent.setup();
    await screen.findByRole("tree", { name: "Location tree" });

    await user.type(screen.getByRole("searchbox", { name: "Filter locations" }), "lab");

    expect(namesIn(screen.getByRole("tree", { name: "Location tree" }))).toEqual(["Lab"]);
  });

  it("filters by short code, in any case", async () => {
    renderLocationsPage();
    const user = userEvent.setup();
    await screen.findByRole("tree", { name: "Location tree" });

    await user.type(screen.getByRole("searchbox", { name: "Filter locations" }), "wx-l-0003");

    expect(namesIn(screen.getByRole("tree", { name: "Location tree" }))).toEqual(["Parts box"]);
  });

  it("says when the filter matches nothing, and shows the whole tree once it is cleared", async () => {
    renderLocationsPage();
    const user = userEvent.setup();
    await screen.findByRole("tree", { name: "Location tree" });
    const filter = screen.getByRole("searchbox", { name: "Filter locations" });

    await user.type(filter, "nowhere");

    expect(screen.getByText("No location matches that.")).toHaveRole("status");
    expect(screen.queryByRole("tree", { name: "Location tree" })).toBeNull();

    await user.clear(filter);
    expect(namesIn(screen.getByRole("tree", { name: "Location tree" }))).toEqual([
      "Lab",
      "Drawer 3",
      "Parts box",
    ]);
  });

  it("is filtered and walked with the keyboard alone, a folded branch opened for its match", async () => {
    renderLocationsPage();
    const user = userEvent.setup();
    const tree = await screen.findByRole("tree", { name: "Location tree" });

    // Fold Lab away first, so its drawer is hidden before the filter runs.
    await tabInto(user, tree);
    await user.keyboard("{ArrowLeft}");
    expect(namesIn(tree)).toEqual(["Lab", "Parts box"]);

    await user.keyboard("{Shift>}{Tab}{/Shift}");
    const filter = screen.getByRole("searchbox", { name: "Filter locations" });
    expect(filter).toHaveFocus();
    await user.keyboard("0002");

    const filtered = screen.getByRole("tree", { name: "Location tree" });
    expect(namesIn(filtered)).toEqual(["Lab", "Drawer 3"]);
    await tabInto(user, filtered);
    await user.keyboard("{ArrowDown}{Enter}");
    expect(await screen.findByRole("heading", { level: 2, name: /Drawer 3/ })).toBeInTheDocument();
  });
});

function namesIn(tree: HTMLElement) {
  return within(tree)
    .getAllByRole("treeitem")
    .map((item) => item.getAttribute("aria-label"));
}
