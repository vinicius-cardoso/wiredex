import { Link } from "@tanstack/react-router";
import type { CategoryNode } from "@wiredex/api-client";
import { type FormEvent, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  FilterField,
  filterButton,
  filterControl,
  listCell,
  listHead,
  listHeadCell,
  listPage,
  listRow,
  listTable,
  PageHeader,
  primaryAction,
  secondaryAction,
  useScrollToStart,
} from "../../shared/ui/list";
import {
  DEFAULT_PAGE_SIZE,
  type PageSize,
  Pagination,
  useClampedPage,
} from "../../shared/ui/pagination";
import { keptWithAncestors, type TreeBranch, TreeFrame, TreeView } from "../../shared/ui/tree";
import { usePartTotals } from "../inventory/inventory";
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
import { usePartSearch } from "./search/search";
import { emptyQuery, type PartQuery } from "./search/searchParams";

/**
 * The category tree and the category picked in it, side by side: on the left a compact tree,
 * one line per category, narrowed by a filter that keeps a match's ancestors in view; on the
 * right the picked category with its fields, its two switches, its rename, move and delete, and
 * the parts filed in it. The header adds a category inside the picked one, or at the top level
 * while none is picked. On a laptop each side scrolls on its own.
 */
export function CategoriesPage() {
  const { t } = useTranslation();
  const filterId = useId();
  const categories = useCategories();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const all = categories.data ?? [];
  const selected = all.find((category) => category.id === selectedId) ?? null;
  const shown = keptWithAncestors(
    all,
    (category) => folded(category.name).includes(folded(filter)),
    (category) => category.id,
    (category) => category.parent_id,
  );
  const roots = branchesOf(categoryTree(shown));

  return (
    <section className={listPage}>
      <PageHeader
        title={t("catalog.categories.title")}
        intro={t("catalog.categories.intro")}
        actions={<NewCategoryForm parent={selected} />}
      />

      {categories.isPending && <p className="text-muted">{t("catalog.categories.loading")}</p>}
      {categories.isError && (
        <p role="alert" className="text-crit">
          {t("catalog.categories.error")}
        </p>
      )}
      {categories.data && all.length === 0 && (
        <p className="max-w-prose rounded-lg border border-dashed border-border-strong bg-surface p-6 text-muted">
          {t("catalog.categories.empty")}
        </p>
      )}

      {all.length > 0 && (
        <div className="grid gap-3 lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(15rem,22rem)_minmax(0,1fr)]">
          <div className="flex min-h-0 flex-col gap-2">
            <FilterField label={t("catalog.categories.filter")} htmlFor={filterId}>
              <div className="flex gap-2">
                <input
                  id={filterId}
                  type="search"
                  value={filter}
                  onChange={(event) => setFilter(event.target.value)}
                  placeholder={t("catalog.categories.filterPlaceholder")}
                  className={`${filterControl} min-w-0 flex-1`}
                />
                {filter !== "" && (
                  <button type="button" onClick={() => setFilter("")} className={filterButton}>
                    {t("catalog.categories.clearFilter")}
                  </button>
                )}
              </div>
            </FilterField>
            {shown.length === 0 && (
              <p role="status" className="text-sm text-muted">
                {t("catalog.categories.filterEmpty")}
              </p>
            )}
            {shown.length > 0 && (
              <TreeFrame>
                <TreeView
                  // A new filter draws the tree afresh, so a branch folded earlier can't hide a
                  // match.
                  key={filter}
                  label={t("catalog.categories.tree")}
                  roots={roots}
                  idOf={(category) => category.id}
                  nameOf={(category) => category.name}
                  detailOf={(category) => <PartCount count={category.part_count} />}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                />
              </TreeFrame>
            )}
          </div>

          <div className="grid min-w-0 content-start gap-3 lg:min-h-0 lg:overflow-y-auto">
            {selected ? (
              <>
                <CategoryActions
                  category={selected}
                  categories={all}
                  onDeleted={() => setSelectedId(null)}
                />
                <CategorySchemaPanel category={selected} />
                {/* Keyed, so another category opens its parts at the first page. */}
                <CategoryParts key={selected.id} category={selected} />
              </>
            ) : (
              <p className="text-muted">{t("catalog.categories.pickOne")}</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

/** The quiet count beside a category's name: how many parts are filed in it. */
function PartCount({ count }: { count: number }) {
  const { t } = useTranslation();
  return (
    <span title={t("catalog.categories.partCount", { count })} className="tabular-nums">
      {count}
    </span>
  );
}

/** The catalog's branches in the tree's shape. */
function branchesOf(branches: CategoryBranch[]): TreeBranch<CategoryNode>[] {
  return branches.map((branch) => ({
    node: branch.category,
    children: branchesOf(branch.children),
  }));
}

/** Text as the filter compares it: case and accents don't count. */
function folded(text: string): string {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().trim();
}

/** The set flag as the control's value: unset is "inherit", the rest their own answer. */
function flagValue(flag: boolean | null): FlagChoice {
  if (flag === null) return "inherit";
  return flag ? "yes" : "no";
}

/** The control's value as the patch sends it: `null` clears the flag back to inheriting. */
function flagSent(choice: FlagChoice): boolean | null {
  return choice === "inherit" ? null : choice === "yes";
}

/**
 * The header's add: a name box and *Add*, which files the new category inside the picked one,
 * or at the top level while none is picked. The box says where the category will go.
 */
function NewCategoryForm({ parent }: { parent: CategoryNode | null }) {
  const { t } = useTranslation();
  const id = useId();
  const whereId = useId();
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
    <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
      <label htmlFor={id} className="sr-only">
        {t("catalog.categories.add")}
      </label>
      <input
        id={id}
        type="text"
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder={
          parent
            ? t("catalog.categories.addPlaceholderUnder", { name: parent.name })
            : t("catalog.categories.addPlaceholderRoot")
        }
        aria-describedby={whereId}
        className={`${filterControl} sm:w-64`}
      />
      <span id={whereId} className="sr-only">
        {parent
          ? t("catalog.categories.addUnder", { name: parent.name })
          : t("catalog.categories.addAtRoot")}
      </span>
      <button type="submit" disabled={create.isPending} className={primaryAction}>
        {t("catalog.categories.create")}
      </button>
      {create.isError && (
        <p role="alert" className="basis-full text-sm text-crit">
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

/** The three answers a tri-state flag control offers (requirement 9.6, 09's 11.10). */
type FlagChoice = "inherit" | "yes" | "no";

/**
 * The picked category: its name, rename, move, its two switches and delete, side by side on a
 * wide screen (requirements 7.7, 7.8).
 */
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

  function track(choice: FlagChoice) {
    // `null` clears the flag back to inheriting; `true`/`false` overrides (requirement 6.2).
    edit.mutate({ categoryId: category.id, body: { tracked_individually: flagSent(choice) } });
  }

  function stock(choice: FlagChoice) {
    edit.mutate({ categoryId: category.id, body: { not_stocked: flagSent(choice) } });
  }

  return (
    <section
      aria-label={t("catalog.categories.selected", { name: category.name })}
      className="grid gap-3 rounded-lg border border-border bg-surface p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="min-w-0 font-display text-xl font-semibold wrap-anywhere">
          {category.name}
        </h2>
        {!asking && (
          <button
            type="button"
            onClick={() => setAsking(true)}
            className="inline-flex h-9 items-center rounded-md border border-crit px-3 text-sm text-crit hover:bg-surface-2"
          >
            {t("catalog.categories.delete")}
          </button>
        )}
      </div>

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
              className="inline-flex h-9 items-center rounded-md bg-crit px-3 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
            >
              {t("catalog.categories.deleteConfirm")}
            </button>
            <button type="button" onClick={() => setAsking(false)} className={secondaryAction}>
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

      <div className="grid items-start gap-x-4 gap-y-3 sm:grid-cols-2 2xl:grid-cols-4">
        <form onSubmit={rename} className="grid gap-1">
          <label htmlFor={nameId} className="text-xs font-medium text-muted">
            {t("catalog.categories.renameLabel")}
          </label>
          <div className="flex gap-2">
            <input
              id={nameId}
              name="name"
              type="text"
              defaultValue={category.name}
              // Remounts with the category, so the box always holds the selected name.
              key={category.id}
              className={filterControl}
            />
            <button type="submit" className={filterButton} disabled={edit.isPending}>
              {t("catalog.categories.rename")}
            </button>
          </div>
        </form>

        <div className="grid gap-1">
          <label htmlFor={parentId} className="text-xs font-medium text-muted">
            {t("catalog.categories.moveLabel")}
          </label>
          <select
            id={parentId}
            value={category.parent_id ?? ""}
            onChange={(event) => move(event.target.value)}
            className={filterControl}
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

        <FlagControl
          keys="catalog.categories.tracking"
          set={category.tracked_individually}
          resolved={category.tracked_individually_resolved}
          onChange={track}
        />
        {/* Beside tracking, and resolved on its own: a board type can be both (09's decision 3). */}
        <FlagControl
          keys="catalog.categories.stocking"
          set={category.not_stocked}
          resolved={category.not_stocked_resolved}
          onChange={stock}
        />
      </div>

      {edit.isError && (
        <p role="alert" className="text-sm text-crit">
          {refusalMessage(edit.error) ?? t("catalog.categories.editError")}
        </p>
      )}
    </section>
  );
}

type FlagProps = {
  /** Where the control's sentences live: `label`, `inherit`, `yes`, `no` and the two resolved. */
  keys: "catalog.categories.tracking" | "catalog.categories.stocking";
  set: boolean | null;
  resolved: boolean;
  onChange: (choice: FlagChoice) => void;
};

/** One category flag as inherit, yes or no, with the answer it inherits while unset. */
function FlagControl({ keys, set, resolved, onChange }: FlagProps) {
  const { t } = useTranslation();
  const id = useId();

  return (
    <div className="grid gap-1">
      <label htmlFor={id} className="text-xs font-medium text-muted">
        {t(`${keys}.label`)}
      </label>
      <select
        id={id}
        value={flagValue(set)}
        onChange={(event) => onChange(event.target.value as FlagChoice)}
        className={filterControl}
      >
        <option value="inherit">{t(`${keys}.inherit`)}</option>
        <option value="yes">{t(`${keys}.yes`)}</option>
        <option value="no">{t(`${keys}.no`)}</option>
      </select>
      {set === null && (
        // The inherited answer, so "inherit" isn't a blank the owner has to reason about
        // (requirement 9.6).
        <p className="text-xs text-muted">
          {resolved ? t(`${keys}.resolvedYes`) : t(`${keys}.resolvedNo`)}
        </p>
      )}
    </div>
  );
}

/**
 * The parts filed in the category itself, by name, each with its part number and stock and
 * linking to its page: one search for the page of parts and one read for their stock. The
 * parts list opens on the same category for the rest. Its page is its own, not the address's,
 * as a record's history is.
 */
function CategoryParts({ category }: { category: CategoryNode }) {
  const { t } = useTranslation();
  const query: PartQuery = {
    ...emptyQuery,
    category: category.id,
    exact: true,
    sort: "name",
    direction: "asc",
  };
  const [page, setPage] = useState(1);
  const [size, setSize] = useState<PageSize>(DEFAULT_PAGE_SIZE);
  const list = useRef<HTMLDivElement>(null);
  const search = usePartSearch(query, page, size);
  useScrollToStart(list, `${page}:${size}`);
  useClampedPage(page, search.isPlaceholderData ? undefined : search.data?.page, setPage);
  const parts = search.data?.items ?? [];
  const shownIds = parts.map((part) => part.id);
  // biome-ignore lint/correctness/useExhaustiveDependencies: the join is the identity we key on.
  const partIds = useMemo(() => shownIds, [shownIds.join(",")]);
  const totals = usePartTotals(partIds);

  return (
    <section
      aria-label={t("catalog.categories.parts.title", { name: category.name })}
      className="grid gap-3 rounded-lg border border-border bg-surface p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-lg font-semibold">
          {t("catalog.categories.parts.heading")}
        </h2>
        <Link
          to="/parts"
          search={{ category: category.id, exact: true }}
          className="text-sm text-primary hover:underline"
        >
          {t("catalog.categories.parts.open")}
        </Link>
      </div>
      {search.isPending && (
        <p className="text-sm text-muted">{t("catalog.categories.parts.loading")}</p>
      )}
      {search.isError && (
        <p role="alert" className="text-sm text-crit">
          {t("catalog.categories.parts.error")}
        </p>
      )}
      {search.data && parts.length === 0 && (
        <p className="text-sm text-muted">{t("catalog.categories.parts.empty")}</p>
      )}
      {parts.length > 0 && (
        // Positioned, so the table's screen-reader-only texts scroll and clip with this box.
        <div ref={list} className="relative overflow-x-auto">
          <table className={listTable}>
            <caption className="sr-only">
              {t("catalog.categories.parts.title", { name: category.name })}
            </caption>
            <thead className={listHead}>
              <tr>
                <th scope="col" className={listHeadCell}>
                  {t("catalog.categories.parts.columns.name")}
                </th>
                <th scope="col" className={listHeadCell}>
                  {t("catalog.categories.parts.columns.mpn")}
                </th>
                <th scope="col" className={`${listHeadCell} text-right`}>
                  {t("catalog.categories.parts.columns.stock")}
                </th>
              </tr>
            </thead>
            <tbody>
              {parts.map((part) => (
                <tr key={part.id} className={listRow}>
                  <th scope="row" className={`${listCell} font-normal`}>
                    <Link
                      to="/parts/$partId"
                      params={{ partId: part.id }}
                      className="text-primary hover:underline"
                    >
                      {part.name}
                    </Link>
                  </th>
                  <td className={`${listCell} font-mono text-xs`}>
                    {part.mpn ?? t("inventory.units.blank")}
                  </td>
                  <td className={`${listCell} text-right tabular-nums`}>
                    {totals.data ? (totals.data.get(part.id) ?? 0) : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {search.data && (
        <Pagination
          label={t("catalog.categories.parts.pages")}
          total={search.data.total}
          page={search.data.page}
          size={size}
          onChange={(next, nextSize) => {
            setPage(next);
            setSize(nextSize);
          }}
        />
      )}
    </section>
  );
}
