import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test/render";
import { aLocation } from "../../test/server";
import { locationTree } from "./inventory";
import { LocationTree } from "./LocationTree";

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

/** Wraps the tree with the selection state a page would own, so Enter has something to set. */
function Harness({ onSelect = vi.fn() }: { onSelect?: (id: string) => void }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  return (
    <LocationTree
      roots={locationTree([lab, drawer, box])}
      selectedId={selectedId}
      onSelect={(id) => {
        setSelectedId(id);
        onSelect(id);
      }}
    />
  );
}

describe("LocationTree", () => {
  it("exposes each location as a treeitem named after it, with its code and counts beside it", () => {
    renderWithProviders(<Harness />);

    const tree = screen.getByRole("tree", { name: "Location tree" });
    const items = within(tree).getAllByRole("treeitem");

    expect(items.map((item) => item.getAttribute("aria-label"))).toEqual([
      "Lab",
      "Drawer 3",
      "Parts box",
    ]);
    // The parent announces it can be folded; a leaf carries no expanded state.
    expect(screen.getByRole("treeitem", { name: "Lab" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("treeitem", { name: "Parts box" })).not.toHaveAttribute(
      "aria-expanded",
    );
    const nested = screen.getByRole("treeitem", { name: "Drawer 3" });
    expect(nested).toHaveAttribute("aria-level", "2");
    expect(nested).toHaveTextContent("WX-L-0002");
    expect(nested).toHaveTextContent("Sublocations: 0 · Lots: 5");
  });

  it("walks with the arrows and picks with Enter", async () => {
    const onSelect = vi.fn();
    renderWithProviders(<Harness onSelect={onSelect} />);
    const user = userEvent.setup();

    await user.tab();
    expect(screen.getByRole("treeitem", { name: "Lab" })).toHaveFocus();

    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("treeitem", { name: "Drawer 3" })).toHaveFocus();

    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith(drawer.id);
    expect(screen.getByRole("treeitem", { name: "Drawer 3" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("folds a branch away with ArrowLeft and opens it again with ArrowRight", async () => {
    renderWithProviders(<Harness />);
    const user = userEvent.setup();
    const tree = screen.getByRole("tree", { name: "Location tree" });

    await user.tab();
    // On the parent: Left folds it, so the child leaves the tree.
    await user.keyboard("{ArrowLeft}");
    expect(within(tree).getAllByRole("treeitem")).toHaveLength(2);
    expect(screen.getByRole("treeitem", { name: "Lab" })).toHaveAttribute("aria-expanded", "false");

    await user.keyboard("{ArrowRight}");
    expect(within(tree).getAllByRole("treeitem")).toHaveLength(3);
    expect(screen.getByRole("treeitem", { name: "Lab" })).toHaveAttribute("aria-expanded", "true");
  });
});
