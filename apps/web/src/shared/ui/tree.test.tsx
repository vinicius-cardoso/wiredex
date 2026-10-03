import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { keptWithAncestors, type TreeBranch, TreeView } from "./tree";

type Place = { id: string; name: string; parent: string | null; code: string };

const lab: Place = { id: "lab", name: "Lab", parent: null, code: "WX-L-0001" };
const drawer: Place = { id: "drawer", name: "Drawer 3", parent: "lab", code: "WX-L-0002" };
const box: Place = { id: "box", name: "Parts box", parent: null, code: "WX-L-0003" };

const ROOTS: TreeBranch<Place>[] = [
  { node: lab, children: [{ node: drawer, children: [] }] },
  { node: box, children: [] },
];

/** The tree with the selection state a page would own, so Enter has something to set. */
function Harness({ onSelect = vi.fn() }: { onSelect?: (id: string) => void }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  return (
    <TreeView
      label="Places"
      roots={ROOTS}
      idOf={(place) => place.id}
      nameOf={(place) => place.name}
      detailOf={(place) => <span className="font-mono">{place.code}</span>}
      selectedId={selectedId}
      onSelect={(id) => {
        setSelectedId(id);
        onSelect(id);
      }}
    />
  );
}

function names(): (string | null)[] {
  return within(screen.getByRole("tree", { name: "Places" }))
    .getAllByRole("treeitem")
    .map((item) => item.getAttribute("aria-label"));
}

describe("TreeView", () => {
  it("names each item after its node, its detail beside it, one line per node", () => {
    render(<Harness />);

    expect(names()).toEqual(["Lab", "Drawer 3", "Parts box"]);
    // A branch announces it can be folded; a leaf carries no expanded state.
    expect(screen.getByRole("treeitem", { name: "Lab" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("treeitem", { name: "Parts box" })).not.toHaveAttribute(
      "aria-expanded",
    );
    const nested = screen.getByRole("treeitem", { name: "Drawer 3" });
    expect(nested).toHaveAttribute("aria-level", "2");
    expect(nested).toHaveTextContent("WX-L-0002");
  });

  it("walks with the arrows and picks with Enter", async () => {
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);
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
    // ArrowLeft from a leaf goes up to its parent, Home and End to the ends.
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("treeitem", { name: "Lab" })).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("treeitem", { name: "Parts box" })).toHaveFocus();
    await user.keyboard("{Home}{ }");
    expect(onSelect).toHaveBeenLastCalledWith(lab.id);
  });

  it("folds a branch away with ArrowLeft and opens it again with ArrowRight", async () => {
    render(<Harness />);
    const user = userEvent.setup();

    await user.tab();
    await user.keyboard("{ArrowLeft}");
    expect(names()).toEqual(["Lab", "Parts box"]);
    expect(screen.getByRole("treeitem", { name: "Lab" })).toHaveAttribute("aria-expanded", "false");

    await user.keyboard("{ArrowRight}");
    expect(names()).toEqual(["Lab", "Drawer 3", "Parts box"]);
    // Right again, on an open branch, steps into its first child.
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("treeitem", { name: "Drawer 3" })).toHaveFocus();
  });

  it("folds a branch with its chevron, and picks a node anywhere else on its line", async () => {
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);
    const user = userEvent.setup();
    const labItem = screen.getByRole("treeitem", { name: "Lab" });

    await user.click(labItem.querySelector("[aria-hidden='true']") as Element);
    expect(names()).toEqual(["Lab", "Parts box"]);
    expect(onSelect).not.toHaveBeenCalled();

    await user.click(within(labItem).getByText("WX-L-0001"));
    expect(onSelect).toHaveBeenCalledWith(lab.id);
  });
});

describe("keptWithAncestors", () => {
  const all = [lab, drawer, box];
  const kept = (text: string) =>
    keptWithAncestors(
      all,
      (place) => place.name.toLowerCase().includes(text),
      (place) => place.id,
      (place) => place.parent,
    ).map((place) => place.name);

  it("keeps each match with its ancestors, in the list's order", () => {
    expect(kept("drawer")).toEqual(["Lab", "Drawer 3"]);
    expect(kept("lab")).toEqual(["Lab"]);
    expect(kept("")).toEqual(["Lab", "Drawer 3", "Parts box"]);
    expect(kept("nowhere")).toEqual([]);
  });

  it("ends a walk up a loop of parents", () => {
    const looped: Place[] = [
      { id: "a", name: "A", parent: "b", code: "1" },
      { id: "b", name: "B", parent: "a", code: "2" },
    ];

    const found = keptWithAncestors(
      looped,
      (place) => place.name === "A",
      (place) => place.id,
      (place) => place.parent,
    );

    expect(found.map((place) => place.name)).toEqual(["A", "B"]);
  });
});
