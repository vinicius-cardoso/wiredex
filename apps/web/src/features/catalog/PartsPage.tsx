import { getRouteApi, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { listPage, PageHeader, primaryAction, secondaryAction } from "../../shared/ui/list";
import { usePartTotals } from "../inventory/inventory";
import { CatalogRefusal, useCategories, useCategorySchema } from "./catalog";
import { FilterPanel } from "./search/FilterPanel";
import { ResultsTable } from "./search/ResultsTable";
import { useFacets, usePartSearch } from "./search/search";
import {
  emptyQuery,
  narrows,
  type PartQuery,
  paramsFromQuery,
  queryFromParams,
  type SortField,
} from "./search/searchParams";

/** How long typing pauses before the address, and so the search, changes (requirement 6.2). */
const DEBOUNCE_MS = 300;

const route = getRouteApi("/authenticated/parts");

/**
 * The parts page as a parametric search. The search itself lives in the address
 * (requirement 6.4): the panel edits a draft that feels instant, and 300 ms after typing
 * stops the draft is written to the URL, which is what the results and facets follow. A
 * refused filter is shown next to it while the last good rows stay on screen (6.5); the
 * empty state offers to clear the filters (6.6).
 */
export function PartsPage() {
  const { t } = useTranslation();
  const params = route.useSearch();
  const query = queryFromParams(params);
  const navigate = route.useNavigate();

  // The panel writes to the draft on every keystroke, so the inputs never lag; a timer then
  // commits it to the address. Sorting and clearing commit at once, without the wait.
  const [draft, setDraft] = useState<PartQuery>(query);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Back and Forward, or a shared link, change the address without touching the draft. When
  // they do, adopt the address as the new draft — the well-known "reset derived state when a
  // prop changes" pattern, done in render rather than an effect so there is no extra paint.
  const address = JSON.stringify(params);
  const lastAddress = useRef(address);
  if (lastAddress.current !== address) {
    lastAddress.current = address;
    setDraft(query);
  }

  useEffect(() => () => clearTimeout(timer.current), []);

  function commit(next: PartQuery) {
    void navigate({ search: paramsFromQuery(next), replace: true });
  }

  function edit(next: PartQuery) {
    setDraft(next);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => commit(next), DEBOUNCE_MS);
  }

  function sortBy(field: SortField) {
    // The active column flips direction; a new column starts descending, like "newest".
    const active = sameField(draft.sort, field);
    const direction: PartQuery["direction"] = active && draft.direction === "desc" ? "asc" : "desc";
    const next: PartQuery = { ...draft, sort: field, direction };
    clearTimeout(timer.current);
    setDraft(next);
    commit(next);
  }

  function clear() {
    clearTimeout(timer.current);
    setDraft(emptyQuery);
    commit(emptyQuery);
  }

  const categories = useCategories();
  const schema = useCategorySchema(query.category);
  const facets = useFacets(query.category, query.text, query.pin);
  const search = usePartSearch(query);

  const attributes = schema.data?.attributes ?? [];
  const results = search.data?.pages.flatMap((page) => page.items) ?? [];
  const refusals = refusalsByKey(search.error);
  const narrowed = narrows(query);

  // The ids on show, so the stock totals for the whole page come back in one query
  // (requirement 7.2). Memoised on the joined ids so a new array with the same ids doesn't
  // change the query key on every render.
  const shownIds = results.map((part) => part.id);
  // biome-ignore lint/correctness/useExhaustiveDependencies: the join is the identity we key on.
  const partIds = useMemo(() => shownIds, [shownIds.join(",")]);
  const totals = usePartTotals(partIds);

  return (
    <section className={listPage}>
      <PageHeader
        title={t("catalog.search.title")}
        intro={t("catalog.search.intro")}
        actions={
          <>
            <Link to="/import" className={secondaryAction}>
              {t("inventory.import.open")}
            </Link>
            <Link to="/parts/new" className={primaryAction}>
              {t("catalog.search.new")}
            </Link>
          </>
        }
      />
      <FilterPanel
        query={draft}
        onChange={edit}
        onClear={clear}
        categories={categories.data}
        attributes={query.category !== null ? attributes : undefined}
        facets={facets.data}
        facetsLoading={facets.isLoading}
        refusals={refusals}
      />
      {search.isPending && <p className="text-muted">{t("catalog.search.loading")}</p>}
      {search.isError && Object.keys(refusals).length === 0 && (
        <p role="alert" className="text-crit">
          {t("catalog.search.error")}
        </p>
      )}
      {search.data && results.length === 0 && (
        <div className="grid max-w-prose justify-items-start gap-3 rounded-lg border border-dashed border-border-strong bg-surface p-6">
          {/* Clearing is in the filter bar, right above, whenever anything narrows the list. */}
          <p className="text-muted">
            {narrowed ? t("catalog.search.noMatches") : t("catalog.search.empty")}
          </p>
        </div>
      )}
      {results.length > 0 && (
        <ResultsTable
          results={results}
          categories={categories.data}
          attributes={query.category !== null ? attributes : []}
          totals={totals.data}
          sort={query.sort}
          direction={query.direction}
          onSort={sortBy}
        />
      )}
      {search.hasNextPage && (
        <button
          type="button"
          onClick={() => void search.fetchNextPage()}
          disabled={search.isFetchingNextPage}
          className="self-start rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2 disabled:opacity-60"
        >
          {t("catalog.search.loadMore")}
        </button>
      )}
    </section>
  );
}

function sameField(a: SortField, b: SortField): boolean {
  if (typeof a === "string" || typeof b === "string") return a === b;
  return a.attribute === b.attribute;
}

/**
 * The API names the filter it refused in its message (`filter resistance: ...`), so a 422 is
 * turned into a message per key, to show next to that filter (requirement 6.5). Anything the
 * message can't be tied to a key falls through to the general error line.
 */
function refusalsByKey(error: unknown): Record<string, string> {
  if (!(error instanceof CatalogRefusal) || error.status !== 422) return {};
  const match = /^filter\s+([^:]+):/i.exec(error.detail);
  const key = match?.[1]?.trim();
  return key ? { [key]: error.detail } : {};
}
