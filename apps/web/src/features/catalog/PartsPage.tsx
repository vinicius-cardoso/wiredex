import type { CategoryNode, PartSummary } from "@wiredex/api-client";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { categoryName, useCategories, useParts } from "./catalog";

const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";
const cell = "py-2 pr-4 align-top";

export function PartsPage() {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const categories = useCategories();
  const parts = useParts({ search, categoryId });

  const rows = parts.data?.pages.flatMap((page) => page.items) ?? [];
  const narrowed = search.trim() !== "" || categoryId !== null;

  return (
    <section className="grid gap-4">
      <h1 className="font-display text-3xl font-semibold tracking-tight">
        {t("catalog.parts.title")}
      </h1>
      <p className="text-muted">{t("catalog.parts.intro")}</p>

      <search>
        <form
          className="flex flex-wrap items-end gap-3"
          // Filtering happens as you type; Enter must not reload the page.
          onSubmit={(event) => event.preventDefault()}
        >
          <label className="grid gap-1 text-sm font-medium">
            {t("catalog.parts.search")}
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t("catalog.parts.searchPlaceholder")}
              className={control}
            />
          </label>
          <label className="grid gap-1 text-sm font-medium">
            {t("catalog.parts.category")}
            <select
              value={categoryId ?? ""}
              onChange={(event) => setCategoryId(event.target.value || null)}
              className={control}
            >
              <option value="">{t("catalog.parts.everyCategory")}</option>
              {(categories.data ?? []).map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </label>
        </form>
      </search>

      {parts.isPending && <p className="text-muted">{t("catalog.parts.loading")}</p>}
      {parts.isError && (
        <p role="alert" className="text-crit">
          {t("catalog.parts.error")}
        </p>
      )}
      {parts.data && rows.length === 0 && (
        <p className="max-w-prose rounded-lg border border-dashed border-border-strong bg-surface p-6 text-muted">
          {narrowed ? t("catalog.parts.noMatches") : t("catalog.parts.empty")}
        </p>
      )}
      {rows.length > 0 && <PartsTable parts={rows} categories={categories.data} />}
      {parts.hasNextPage && (
        <button
          type="button"
          onClick={() => void parts.fetchNextPage()}
          disabled={parts.isFetchingNextPage}
          className="justify-self-start rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2 disabled:opacity-60"
        >
          {t("catalog.parts.loadMore")}
        </button>
      )}
    </section>
  );
}

type TableProps = { parts: PartSummary[]; categories: CategoryNode[] | undefined };

function PartsTable({ parts, categories }: TableProps) {
  const { t } = useTranslation();
  const columns = ["name", "category", "manufacturer", "mpn", "package"] as const;

  return (
    <table className="w-full border-collapse text-left text-sm">
      <caption className="sr-only">{t("catalog.parts.list")}</caption>
      <thead>
        <tr className="border-b border-border text-muted">
          {columns.map((column) => (
            <th key={column} scope="col" className={`${cell} font-medium`}>
              {t(`catalog.parts.columns.${column}`)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {parts.map((part) => (
          <tr key={part.id} className="border-b border-border">
            <th scope="row" className={`${cell} font-medium`}>
              {part.name}
            </th>
            <td className={cell}>{categoryName(categories, part.category_id) ?? blank}</td>
            <td className={cell}>{part.manufacturer ?? blank}</td>
            <td className={`${cell} font-mono`}>{part.mpn ?? blank}</td>
            <td className={cell}>{part.package ?? blank}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** An em dash for what a part doesn't carry: the same in both languages, so not a key. */
const blank = "—";
