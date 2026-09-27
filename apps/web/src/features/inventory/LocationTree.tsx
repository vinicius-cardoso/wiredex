import type { LocationNode } from "@wiredex/api-client";
import { type KeyboardEvent, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { LocationBranch } from "./inventory";

/** A row of the tree as it is drawn: flat, with the depth it sits at. */
type Row = { location: LocationNode; level: number; children: number; open: boolean };

type TreeProps = {
  roots: LocationBranch[];
  selectedId: string | null;
  onSelect: (locationId: string) => void;
};

/**
 * The tree, as a flat list of `treeitem`s carrying their own depth (requirement 9.8).
 *
 * One item at a time is in the tab order and the arrows move between them, which is the tree
 * pattern: Tab reaches the tree, the arrows walk it, Enter picks a location, and Left and
 * Right fold a branch away or open it again. Each item is named by the location's name, with
 * its short code and counts beside it as decoration.
 */
export function LocationTree({ roots, selectedId, onSelect }: TreeProps) {
  const { t } = useTranslation();
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set());
  const [focusedId, setFocusedId] = useState<string | null>(null);

  const tree = useRef<HTMLUListElement>(null);
  const rows = visibleRows(roots, closed);
  const focused = rows.find((row) => row.location.id === focusedId) ?? rows[0];

  /** Moves the one item in the tab order, and the focus with it: the roving tabindex. */
  function focusAt(index: number) {
    const at = Math.min(Math.max(index, 0), rows.length - 1);
    const row = rows[at];
    if (!row) return;
    setFocusedId(row.location.id);
    // The items are the list's children in the same order, so the row index is the node.
    const item = tree.current?.children[at];
    if (item instanceof HTMLElement) item.focus();
  }

  function fold(row: Row, open: boolean) {
    setClosed((previous) => {
      const next = new Set(previous);
      if (open) next.delete(row.location.id);
      else next.add(row.location.id);
      return next;
    });
  }

  function onKeyDown(event: KeyboardEvent<HTMLUListElement>) {
    if (!focused) return;
    const at = rows.indexOf(focused);
    const keys: Record<string, () => void> = {
      ArrowDown: () => focusAt(at + 1),
      ArrowUp: () => focusAt(at - 1),
      Home: () => focusAt(0),
      End: () => focusAt(rows.length - 1),
      ArrowRight: () => {
        if (focused.children === 0) return;
        if (focused.open) focusAt(at + 1);
        else fold(focused, true);
      },
      ArrowLeft: () => {
        if (focused.children > 0 && focused.open) fold(focused, false);
        else focusAt(parentIndexOf(rows, at));
      },
      Enter: () => onSelect(focused.location.id),
      " ": () => onSelect(focused.location.id),
    };
    const handler = keys[event.key];
    if (!handler) return;
    event.preventDefault();
    handler();
  }

  return (
    <ul
      ref={tree}
      // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: a tree is what this is.
      role="tree"
      aria-label={t("inventory.locations.tree")}
      onKeyDown={onKeyDown}
      className="grid gap-1"
    >
      {rows.map((row) => (
        <TreeItem
          key={row.location.id}
          row={row}
          selected={row.location.id === selectedId}
          focused={row.location.id === focused?.location.id}
          onSelect={() => onSelect(row.location.id)}
          onFocus={() => setFocusedId(row.location.id)}
        />
      ))}
    </ul>
  );
}

type ItemProps = {
  row: Row;
  selected: boolean;
  focused: boolean;
  onSelect: () => void;
  onFocus: () => void;
};

function TreeItem({ row, selected, focused, onSelect, onFocus }: ItemProps) {
  const { t } = useTranslation();
  const { location } = row;

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: the tree above handles the keys for every item.
    <li
      role="treeitem"
      // The name is spelled out rather than read off the row, so the code and counts beside it
      // stay decoration and the item is found by the name the owner gave it.
      aria-label={location.name}
      aria-level={row.level}
      aria-selected={selected}
      {...(row.children > 0 ? { "aria-expanded": row.open } : {})}
      tabIndex={focused ? 0 : -1}
      onClick={onSelect}
      onFocus={onFocus}
      style={{ marginInlineStart: `${(row.level - 1) * 1.25}rem` }}
      className={`flex cursor-pointer flex-wrap items-baseline gap-x-3 rounded-lg border px-4 py-2 ${
        selected ? "border-primary bg-surface-2" : "border-border bg-surface"
      }`}
    >
      <span className="font-medium">{location.name}</span>
      <span className="font-mono text-sm text-muted">{location.code}</span>
      <span className="text-sm text-muted">
        {t("inventory.locations.counts", {
          children: location.child_count,
          lots: location.lot_count,
        })}
      </span>
    </li>
  );
}

function visibleRows(branches: LocationBranch[], closed: ReadonlySet<string>, level = 1): Row[] {
  return branches.flatMap((branch) => {
    const open = branch.children.length > 0 && !closed.has(branch.location.id);
    const row: Row = {
      location: branch.location,
      level,
      children: branch.children.length,
      open,
    };
    return open ? [row, ...visibleRows(branch.children, closed, level + 1)] : [row];
  });
}

/** The row above that sits one level up, which is where ArrowLeft goes from a leaf. */
function parentIndexOf(rows: Row[], at: number): number {
  const level = rows[at]?.level ?? 1;
  for (let index = at - 1; index >= 0; index -= 1) {
    if ((rows[index]?.level ?? 1) < level) return index;
  }
  return at;
}
