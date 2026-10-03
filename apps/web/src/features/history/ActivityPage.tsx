import { getRouteApi } from "@tanstack/react-router";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  FilterBar,
  FilterField,
  filterButton,
  filterControl,
  listPage,
  PageHeader,
} from "../../shared/ui/list";
import { ChangeList } from "./ChangeList";
import { type ActivitySearch, HISTORY_ACTIONS, RECORD_KINDS, useActivity } from "./history";
import { actionKey, recordKindKey } from "./labels";

/** How long typing pauses before the address, and so the list, changes. */
const DEBOUNCE_MS = 300;

const route = getRouteApi("/authenticated/activity");

/**
 * The workspace's activity (requirement 7.2): every change, newest first, 50 at a time, each a
 * folded block. One bar narrows it by what a change did, the kind of its record and a fragment
 * of the record's name, all kept in the address (`action`, `kind`, `q`) and asked of the API.
 * It takes the page's whole width, two columns of blocks on a wide screen, and on a laptop the
 * blocks scroll inside their own area under the header.
 */
export function ActivityPage() {
  const { t } = useTranslation();
  const search = route.useSearch();
  const activity = useActivity(search);
  const changes = activity.data?.pages.flatMap((page) => page.changes) ?? [];
  const narrowed =
    search.action !== undefined || search.kind !== undefined || search.q !== undefined;

  return (
    <section className={listPage}>
      <PageHeader title={t("history.title")} intro={t("history.intro")} />
      <ActivityFilters search={search} />
      {activity.isPending && <p className="text-muted">{t("history.loading")}</p>}
      {activity.isError && (
        <p role="alert" className="text-crit">
          {t("history.error")}
        </p>
      )}
      {activity.isSuccess && (
        <div className="lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
          <ChangeList
            changes={changes}
            showRecord
            wide
            hasMore={activity.hasNextPage}
            loadingMore={activity.isFetchingNextPage}
            onMore={() => void activity.fetchNextPage()}
            {...(narrowed ? { emptyText: t("history.noMatches") } : {})}
          />
        </div>
      )}
    </section>
  );
}

/** What one filter change sets; the rest of the search rides along as it is. */
type Change = { q?: string; action?: string; kind?: string };

/**
 * The activity's one bar. The box edits a draft that feels instant, written to the address
 * once typing pauses; a select writes at once.
 */
function ActivityFilters({ search }: { search: ActivitySearch }) {
  const { t } = useTranslation();
  const navigate = route.useNavigate();
  const searchId = useId();
  const actionId = useId();
  const kindId = useId();
  const q = search.q ?? "";
  const [draft, setDraft] = useState(q);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Back, Forward or a shared link change the address without touching the draft; adopt the
  // address's text then, in render rather than an effect, so there is no extra paint.
  const lastQ = useRef(q);
  if (lastQ.current !== q) {
    lastQ.current = q;
    setDraft(q);
  }

  useEffect(() => () => clearTimeout(timer.current), []);

  function commit(next: ActivitySearch) {
    void navigate({ search: next, replace: true });
  }

  /** The address for the filters, the one being changed taken from `change`. */
  function searchFor(change: Change): ActivitySearch {
    const next: ActivitySearch = {};
    const action = HISTORY_ACTIONS.find((known) => known === (change.action ?? search.action));
    if (action) next.action = action;
    const kind = RECORD_KINDS.find((known) => known === (change.kind ?? search.kind));
    if (kind) next.kind = kind;
    const text = (change.q ?? draft).trim();
    if (text) next.q = text;
    return next;
  }

  function type(text: string) {
    setDraft(text);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => commit(searchFor({ q: text })), DEBOUNCE_MS);
  }

  function choose(change: { action: string } | { kind: string }) {
    clearTimeout(timer.current);
    commit(searchFor(change));
  }

  function clear() {
    clearTimeout(timer.current);
    setDraft("");
    commit({});
  }

  const narrowed =
    search.action !== undefined || search.kind !== undefined || search.q !== undefined;

  return (
    <FilterBar>
      <FilterField label={t("history.search")} htmlFor={searchId} grow>
        <input
          id={searchId}
          type="search"
          value={draft}
          placeholder={t("history.searchPlaceholder")}
          onChange={(event) => type(event.target.value)}
          className={filterControl}
        />
      </FilterField>
      <FilterField label={t("history.actionFilter")} htmlFor={actionId}>
        <select
          id={actionId}
          value={search.action ?? ""}
          onChange={(event) => choose({ action: event.target.value })}
          className={`${filterControl} sm:w-56`}
        >
          <option value="">{t("history.anyAction")}</option>
          {HISTORY_ACTIONS.map((action) => (
            <option key={action} value={action}>
              {t(actionKey(action))}
            </option>
          ))}
        </select>
      </FilterField>
      <FilterField label={t("history.kindFilter")} htmlFor={kindId}>
        <select
          id={kindId}
          value={search.kind ?? ""}
          onChange={(event) => choose({ kind: event.target.value })}
          className={`${filterControl} sm:w-44`}
        >
          <option value="">{t("history.anyKind")}</option>
          {RECORD_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {t(recordKindKey(kind))}
            </option>
          ))}
        </select>
      </FilterField>
      {(narrowed || draft !== "") && (
        <button type="button" onClick={clear} className={filterButton}>
          {t("history.clear")}
        </button>
      )}
    </FilterBar>
  );
}
