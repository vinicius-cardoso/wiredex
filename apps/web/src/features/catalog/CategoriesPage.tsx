import type { CategoryNode } from "@wiredex/api-client";
import { type FormEvent, type KeyboardEvent, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CategorySchemaPanel } from "./CategorySchemaPanel";
import {
  type CategoryBranch,
  categoryTree,
  refusalMessage,
  useCategories,
  useCreateCategory,
  useDeleteCategory,
  useEditCategory,
} from "./catalog";

const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";
const action = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";

export function CategoriesPage() {
  const { t } = useTranslation();
  const categories = useCategories();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const all = categories.data ?? [];
  const roots = categoryTree(all);
  const selected = all.find((category) => category.id === selectedId) ?? null;

  return (
    <section className="grid gap-4">
      <h1 className="font-display text-3xl font-semibold tracking-tight">
        {t("catalog.categories.title")}
      </h1>
      <p className="text-muted">{t("catalog.categories.intro")}</p>

      {categories.isPending && <p className="text-muted">{t("catalog.categories.loading")}</p>}
      {categories.isError && (
        <p role="alert" className="text-crit">
          {t("catalog.categories.error")}
        </p>
      )}

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <div className="grid gap-4">
          <NewCategoryForm parent={selected} />
          {categories.data && roots.length === 0 && (
            <p className="max-w-prose rounded-lg border border-dashed border-border-strong bg-surface p-6 text-muted">
              {t("catalog.categories.empty")}
            </p>
          )}
          {roots.length > 0 && (
            <CategoryTree roots={roots} selectedId={selectedId} onSelect={setSelectedId} />
          )}
        </div>
        {selected && (
          <div className="grid gap-4">
            <CategoryActions
              category={selected}
              categories={all}
              onDeleted={() => setSelectedId(null)}
            />
            <CategorySchemaPanel category={selected} />
          </div>
        )}
        {!selected && roots.length > 0 && (
          <p className="text-muted">{t("catalog.categories.pickOne")}</p>
        )}
      </div>
    </section>
  );
}

/** A row of the tree as it is drawn: flat, with the depth it sits at. */
type Row = { category: CategoryNode; level: number; children: number; open: boolean };

type TreeProps = {
  roots: CategoryBranch[];
  selectedId: string | null;
  onSelect: (categoryId: string) => void;
};

/**
 * The tree, as a flat list of `treeitem`s carrying their own depth (requirement 7.10).
 *
 * One item at a time is in the tab order and the arrows move between them, which is the tree
 * pattern: Tab reaches the tree, the arrows walk it, Enter picks a category, and Left and
 * Right fold a branch away or open it again.
 */
function CategoryTree({ roots, selectedId, onSelect }: TreeProps) {
  const { t } = useTranslation();
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set());
  const [focusedId, setFocusedId] = useState<string | null>(null);

  const tree = useRef<HTMLUListElement>(null);
  const rows = visibleRows(roots, closed);
  const focused = rows.find((row) => row.category.id === focusedId) ?? rows[0];

  /** Moves the one item in the tab order, and the focus with it: the roving tabindex. */
  function focusAt(index: number) {
    const at = Math.min(Math.max(index, 0), rows.length - 1);
    const row = rows[at];
    if (!row) return;
    setFocusedId(row.category.id);
    // The items are the list's children in the same order, so the row index is the node.
    const item = tree.current?.children[at];
    if (item instanceof HTMLElement) item.focus();
  }

  function fold(row: Row, open: boolean) {
    setClosed((previous) => {
      const next = new Set(previous);
      if (open) next.delete(row.category.id);
      else next.add(row.category.id);
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
      Enter: () => onSelect(focused.category.id),
      " ": () => onSelect(focused.category.id),
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
      aria-label={t("catalog.categories.tree")}
      onKeyDown={onKeyDown}
      className="grid gap-1"
    >
      {rows.map((row) => (
        <TreeItem
          key={row.category.id}
          row={row}
          selected={row.category.id === selectedId}
          focused={row.category.id === focused?.category.id}
          onSelect={() => onSelect(row.category.id)}
          onFocus={() => setFocusedId(row.category.id)}
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
  const { category } = row;

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: the tree above handles the keys for every item.
    <li
      role="treeitem"
      // The name is spelled out rather than read off the row, so the counts beside it stay
      // decoration and the item is found by the name the owner gave it.
      aria-label={category.name}
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
      <span className="font-medium">{category.name}</span>
      <span className="text-sm text-muted">
        {t("catalog.categories.counts", {
          children: category.child_count,
          parts: category.part_count,
        })}
      </span>
    </li>
  );
}

function visibleRows(branches: CategoryBranch[], closed: ReadonlySet<string>, level = 1): Row[] {
  return branches.flatMap((branch) => {
    const open = branch.children.length > 0 && !closed.has(branch.category.id);
    const row: Row = {
      category: branch.category,
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

function NewCategoryForm({ parent }: { parent: CategoryNode | null }) {
  const { t } = useTranslation();
  const id = useId();
  const [name, setName] = useState("");
  const create = useCreateCategory();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (name.trim() === "") return;
    create.mutate(
      { name: name.trim(), parent_id: parent?.id ?? null },
      { onSuccess: () => setName("") },
    );
  }

  return (
    <form onSubmit={submit} className="grid gap-2 rounded-lg border border-border bg-surface p-4">
      <label htmlFor={id} className="text-sm font-medium">
        {t("catalog.categories.add")}
      </label>
      <p className="text-sm text-muted">
        {parent
          ? t("catalog.categories.addUnder", { name: parent.name })
          : t("catalog.categories.addAtRoot")}
      </p>
      <div className="flex flex-wrap gap-2">
        <input
          id={id}
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          className={control}
        />
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded-md bg-primary px-4 py-2 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {t("catalog.categories.create")}
        </button>
      </div>
      {create.isError && (
        <p role="alert" className="text-sm text-crit">
          {refusalMessage(create.error) ?? t("catalog.categories.createError")}
        </p>
      )}
    </form>
  );
}

type ActionProps = {
  category: CategoryNode;
  categories: CategoryNode[];
  onDeleted: () => void;
};

/** Rename, move and delete for the category the tree has selected (requirements 7.7, 7.8). */
function CategoryActions({ category, categories, onDeleted }: ActionProps) {
  const { t } = useTranslation();
  const nameId = useId();
  const parentId = useId();
  const edit = useEditCategory();
  const remove = useDeleteCategory();
  const [asking, setAsking] = useState(false);

  function rename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const named = new FormData(event.currentTarget).get("name");
    const name = String(named ?? "").trim();
    if (name === "" || name === category.name) return;
    edit.mutate({ categoryId: category.id, body: { name } });
  }

  function move(parent: string) {
    edit.mutate({ categoryId: category.id, body: { parent_id: parent === "" ? null : parent } });
  }

  return (
    <section
      aria-label={t("catalog.categories.selected", { name: category.name })}
      className="grid gap-3 rounded-lg border border-border bg-surface p-4"
    >
      <h2 className="font-display text-xl font-semibold">{category.name}</h2>

      <form onSubmit={rename} className="grid gap-2">
        <label htmlFor={nameId} className="text-sm font-medium">
          {t("catalog.categories.renameLabel")}
        </label>
        <div className="flex flex-wrap gap-2">
          <input
            id={nameId}
            name="name"
            type="text"
            defaultValue={category.name}
            // Remounts with the category, so the box always holds the selected name.
            key={category.id}
            className={control}
          />
          <button type="submit" className={action} disabled={edit.isPending}>
            {t("catalog.categories.rename")}
          </button>
        </div>
      </form>

      <div className="grid gap-2">
        <label htmlFor={parentId} className="text-sm font-medium">
          {t("catalog.categories.moveLabel")}
        </label>
        <select
          id={parentId}
          value={category.parent_id ?? ""}
          onChange={(event) => move(event.target.value)}
          className={control}
        >
          <option value="">{t("catalog.categories.moveRoot")}</option>
          {categories
            .filter((candidate) => candidate.id !== category.id)
            .map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.name}
              </option>
            ))}
        </select>
      </div>

      {edit.isError && (
        <p role="alert" className="text-sm text-crit">
          {refusalMessage(edit.error) ?? t("catalog.categories.editError")}
        </p>
      )}

      {!asking && (
        <button
          type="button"
          onClick={() => setAsking(true)}
          className="justify-self-start rounded-md border border-crit px-3 py-1.5 text-sm text-crit hover:bg-surface-2"
        >
          {t("catalog.categories.delete")}
        </button>
      )}
      {asking && (
        <fieldset className="grid gap-2">
          <legend className="text-sm">
            {t("catalog.categories.deleteQuestion", { name: category.name })}
          </legend>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={remove.isPending}
              onClick={() =>
                remove.mutate(category.id, {
                  onSuccess: () => {
                    setAsking(false);
                    onDeleted();
                  },
                })
              }
              className="rounded-md bg-crit px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
            >
              {t("catalog.categories.deleteConfirm")}
            </button>
            <button type="button" onClick={() => setAsking(false)} className={action}>
              {t("catalog.categories.deleteCancel")}
            </button>
          </div>
          {/* The refusal stays here, beside the button that asked for it (requirement 7.8). */}
          {remove.isError && (
            <p role="alert" className="text-sm text-crit">
              {refusalMessage(remove.error) ?? t("catalog.categories.deleteError")}
            </p>
          )}
        </fieldset>
      )}
    </section>
  );
}
