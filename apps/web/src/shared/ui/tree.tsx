import { type KeyboardEvent, type ReactNode, useRef, useState } from "react";
import { ChevronRightIcon } from "./icons";

/** A node with the branch below it, which is how a tree is drawn. */
export type TreeBranch<T> = { node: T; children: TreeBranch<T>[] };

/** A row of the tree as it is drawn: flat, with the depth it sits at. */
type Row<T> = { node: T; id: string; level: number; children: number; open: boolean };

type Props<T> = {
  /** The tree's accessible name. */
  label: string;
  roots: TreeBranch<T>[];
  idOf: (node: T) => string;
  /** What names an item: the name the owner gave it, and nothing else on its line. */
  nameOf: (node: T) => string;
  /** What follows the name on its line, a count or a code: decoration beside the name. */
  detailOf?: (node: T) => ReactNode;
  selectedId: string | null;
  onSelect: (id: string) => void;
};

/**
 * A compact tree, one line per node, as a flat list of `treeitem`s carrying their own depth.
 *
 * One item at a time is in the tab order and the arrows move between them, which is the tree
 * pattern: Tab reaches the tree, the arrows walk it, Enter or Space picks a node, and Left and
 * Right fold a branch away or open it again. A pointer folds a branch with its chevron and
 * picks a node anywhere else on its line. Every branch starts open; a parent that remounts it
 * with a new key, as a filter does, opens every branch again.
 */
export function TreeView<T>({
  label,
  roots,
  idOf,
  nameOf,
  detailOf,
  selectedId,
  onSelect,
}: Props<T>) {
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set());
  const [focusedId, setFocusedId] = useState<string | null>(null);

  const tree = useRef<HTMLUListElement>(null);
  const rows = visibleRows(roots, closed, idOf);
  const focused =
    rows.find((row) => row.id === focusedId) ??
    rows.find((row) => row.id === selectedId) ??
    rows[0];

  /** Moves the one item in the tab order, and the focus with it: the roving tabindex. */
  function focusAt(index: number) {
    const at = Math.min(Math.max(index, 0), rows.length - 1);
    const row = rows[at];
    if (!row) return;
    setFocusedId(row.id);
    // The items are the list's children in the same order, so the row index is the node.
    const item = tree.current?.children[at];
    if (item instanceof HTMLElement) item.focus();
  }

  function fold(row: Row<T>, open: boolean) {
    setClosed((previous) => {
      const next = new Set(previous);
      if (open) next.delete(row.id);
      else next.add(row.id);
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
      Enter: () => onSelect(focused.id),
      " ": () => onSelect(focused.id),
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
      aria-label={label}
      onKeyDown={onKeyDown}
      className="grid"
    >
      {rows.map((row) => {
        const selected = row.id === selectedId;
        return (
          // biome-ignore lint/a11y/useKeyWithClickEvents: the tree above handles the keys for every item.
          <li
            key={row.id}
            role="treeitem"
            // The name is spelled out rather than read off the line, so what sits beside it
            // stays decoration and the item is found by the name the owner gave it.
            aria-label={nameOf(row.node)}
            aria-level={row.level}
            aria-selected={selected}
            {...(row.children > 0 ? { "aria-expanded": row.open } : {})}
            tabIndex={row.id === focused?.id ? 0 : -1}
            onClick={() => onSelect(row.id)}
            onFocus={() => setFocusedId(row.id)}
            style={{ paddingInlineStart: `${(row.level - 1) * 1.125 + 0.25}rem` }}
            className={`flex h-8 min-w-0 cursor-pointer items-center gap-1 rounded-md pr-2 text-sm focus-visible:-outline-offset-2 ${
              selected ? "bg-surface-2 font-semibold text-primary" : "hover:bg-surface-2/60"
            }`}
          >
            {row.children > 0 ? (
              // The pointer's way to fold a branch. The arrows do it from the keyboard, so the
              // chevron stays out of the tab order and hidden from assistive technology.
              <span
                aria-hidden="true"
                onClick={(event) => {
                  event.stopPropagation();
                  fold(row, !row.open);
                }}
                className="inline-flex size-6 shrink-0 items-center justify-center rounded text-muted hover:bg-surface-2 hover:text-text"
              >
                <span className={`transition-transform ${row.open ? "rotate-90" : ""}`}>
                  <ChevronRightIcon />
                </span>
              </span>
            ) : (
              <span aria-hidden="true" className="size-6 shrink-0" />
            )}
            <span className="truncate">{nameOf(row.node)}</span>
            {detailOf && (
              <span className="ml-auto flex shrink-0 items-baseline gap-2 pl-2 text-xs font-normal text-muted">
                {detailOf(row.node)}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function visibleRows<T>(
  branches: TreeBranch<T>[],
  closed: ReadonlySet<string>,
  idOf: (node: T) => string,
  level = 1,
): Row<T>[] {
  return branches.flatMap((branch) => {
    const id = idOf(branch.node);
    const open = branch.children.length > 0 && !closed.has(id);
    const row: Row<T> = { node: branch.node, id, level, children: branch.children.length, open };
    return open ? [row, ...visibleRows(branch.children, closed, idOf, level + 1)] : [row];
  });
}

/** The row above that sits one level up, which is where ArrowLeft goes from a leaf. */
function parentIndexOf<T>(rows: Row<T>[], at: number): number {
  const level = rows[at]?.level ?? 1;
  for (let index = at - 1; index >= 0; index -= 1) {
    if ((rows[index]?.level ?? 1) < level) return index;
  }
  return at;
}

/**
 * The nodes a filter keeps, each with its ancestors, so the tree still shows where a match
 * sits. Blank text keeps them all. The list keeps its order, which is the order the tree draws.
 */
export function keptWithAncestors<T>(
  all: readonly T[],
  matches: (node: T) => boolean,
  idOf: (node: T) => string,
  parentOf: (node: T) => string | null,
): T[] {
  const byId = new Map(all.map((node): [string, T] => [idOf(node), node]));
  const kept = new Set<string>();
  for (const node of all) {
    if (!matches(node)) continue;
    let at: T | undefined = node;
    // Stops at a node already kept: its ancestors are kept too, and a loop ends there.
    while (at && !kept.has(idOf(at))) {
      kept.add(idOf(at));
      const parent = parentOf(at);
      at = parent === null ? undefined : byId.get(parent);
    }
  }
  return all.filter((node) => kept.has(idOf(node)));
}

/** The frame a tree sits in: on a laptop it takes the height left and scrolls inside itself. */
export function TreeFrame({ children }: { children: ReactNode }) {
  return (
    <div
      data-tour="tree"
      className="min-h-0 overflow-auto rounded-lg border border-border bg-surface p-1 lg:flex-1"
    >
      {children}
    </div>
  );
}
