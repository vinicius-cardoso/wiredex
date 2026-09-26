import { getRouteApi, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CatalogRefusal, useCategories, useCategorySchema } from "./catalog";
import { FilterPanel } from "./search/FilterPanel";
import { ResultsTable } from "./search/ResultsTable";
import { useFacets, usePartSearch } from "./search/search";
import {
  emptyQuery,
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
  const narrowed = !isEmpty(query);

  return (
    <section className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-3xl font-semibold tracking-tight">
          {t("catalog.search.title")}
        </h1>
        <Link
          to="/parts/new"
          className="rounded-md bg-primary px-4 py-2 font-semibold text-on-primary hover:opacity-90"
        >
          {t("catalog.search.new")}
        </Link>
      </div>
      <p className="text-muted">{t("catalog.search.intro")}</p>

      <div className="grid gap-4 lg:grid-cols-[20rem_1fr]">
        <FilterPanel
          query={draft}
          onChange={edit}
          categories={categories.data}
          attributes={query.category !== null ? attributes : undefined}
          facets={facets.data}
          facetsLoading={facets.isLoading}
          refusals={refusals}
        />

        <div className="grid content-start gap-4">
          {search.isPending && <p className="text-muted">{t("catalog.search.loading")}</p>}
          {search.isError && Object.keys(refusals).length === 0 && (
            <p role="alert" className="text-crit">
              {t("catalog.search.error")}
            </p>
          )}
          {search.data && results.length === 0 && (
            <div className="grid max-w-prose justify-items-start gap-3 rounded-lg border border-dashed border-border-strong bg-surface p-6">
              <p className="text-muted">
                {narrowed ? t("catalog.search.noMatches") : t("catalog.search.empty")}
              </p>
              {narrowed && (
                <button
                  type="button"
                  onClick={clear}
                  className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
                >
                  {t("catalog.search.clear")}
                </button>
              )}
            </div>
          )}
          {results.length > 0 && (
            <ResultsTable
              results={results}
              categories={categories.data}
              attributes={query.category !== null ? attributes : []}
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
              className="justify-self-start rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2 disabled:opacity-60"
            >
              {t("catalog.search.loadMore")}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}

function sameField(a: SortField, b: SortField): boolean {
  if (typeof a === "string" || typeof b === "string") return a === b;
  return a.attribute === b.attribute;
}

/** A search that narrows nothing, so its empty result is "no parts yet", not "no match". */
function isEmpty(query: PartQuery): boolean {
  return (
    query.text.trim() === "" &&
    query.category === null &&
    query.pin.trim() === "" &&
    query.filters.length === 0
  );
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
