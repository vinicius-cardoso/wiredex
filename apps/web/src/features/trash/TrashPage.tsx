import { getRouteApi, Link } from "@tanstack/react-router";
import type { TrashedItem } from "@wiredex/api-client";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  FilterBar,
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
  TableFrame,
} from "../../shared/ui/list";
import {
  keepSize,
  Pagination,
  pageOfSearch,
  useClampedPage,
  withPage,
} from "../../shared/ui/pagination";
import { kindKey, TRASH_KINDS } from "./kinds";
import {
  type TrashSearch,
  useDeleteForGood,
  useEmptyTrash,
  useRestoreFromTrash,
  useTrash,
} from "./trash";

/** How long typing pauses before the address, and so the list, changes. */
const DEBOUNCE_MS = 300;

const route = getRouteApi("/authenticated/trash");

/**
 * What the page says after a write on one record: it is back, or the write didn't happen. Kept
 * by the page rather than the row, since the refresh after either takes a row that is no
 * longer in the trash off the list.
 */
type Notice =
  | { kind: "restored"; item: TrashedItem }
  | { kind: "failed"; action: "restore" | "delete" };

type Feedback = {
  restored: (item: TrashedItem) => void;
  failed: (action: "restore" | "delete") => void;
};

/**
 * The trash (requirements 9.3 to 9.6): what was moved there, newest first, a numbered page at
 * a time with the bar under the table. One bar narrows it by a kind and a fragment of a name or
 * detail, both kept in the address (`kind`, `q`) with the page and its size (`page`, `size`).
 * A record restored leaves the list, and a notice says it is back with a link to its page;
 * deleting one for good asks in its row, and emptying the trash asks first, since neither can
 * be undone.
 */
export function TrashPage() {
  const { t } = useTranslation();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const { page, size } = pageOfSearch(search);
  const trash = useTrash(search);
  const [notice, setNotice] = useState<Notice | null>(null);
  const items = trash.data?.items ?? [];
  // A page past the end opens the last one, and the address says so: a hand-edited link, or
  // the last record of the last page restored or deleted. A placeholder from the page before
  // doesn't count.
  useClampedPage(
    page,
    trash.isPlaceholderData ? undefined : trash.data?.page,
    (served) => void navigate({ search: (prev) => withPage(prev, served, size), replace: true }),
  );
  const narrowed = search.kind !== undefined || search.q !== undefined;
  const feedback: Feedback = {
    restored: (item) => setNotice({ kind: "restored", item }),
    failed: (action) => setNotice({ kind: "failed", action }),
  };

  return (
    <section className={listPage}>
      <PageHeader
        title={t("trash.title")}
        intro={t("trash.intro")}
        // Emptying takes everything, shown or not: a narrowed list that shows nothing may
        // still sit on a full trash.
        actions={(items.length > 0 || narrowed) && <EmptyTrash onEmptied={() => setNotice(null)} />}
      />
      <TrashFilters search={search} />

      {/* Always rendered, so a screen reader hears the notice when it appears. */}
      <div role="status">
        {notice?.kind === "restored" && <RestoredNotice item={notice.item} />}
      </div>
      {notice?.kind === "failed" && (
        <p role="alert" className="text-crit">
          {notice.action === "restore" ? t("trash.restoreError") : t("trash.deleteError")}
        </p>
      )}

      {trash.isPending && <p className="text-muted">{t("trash.loading")}</p>}
      {trash.isError && (
        <p role="alert" className="text-crit">
          {t("trash.error")}
        </p>
      )}
      {trash.isSuccess && items.length === 0 && (
        <div className="max-w-prose rounded-lg border border-dashed border-border-strong bg-surface p-6">
          <p className="text-muted">{narrowed ? t("trash.noMatches") : t("trash.empty")}</p>
        </div>
      )}
      {items.length > 0 && (
        <TrashTable items={items} feedback={feedback} scrollKey={`${page}:${size}`} />
      )}
      {trash.isSuccess && (
        <Pagination
          label={t("trash.pages")}
          total={trash.data.total}
          page={trash.data.page}
          size={size}
          onChange={(next, nextSize) =>
            void navigate({ search: (prev) => withPage(prev, next, nextSize) })
          }
        />
      )}
    </section>
  );
}

/**
 * The trash's one bar: a search box and a kind. The box edits a draft that feels instant,
 * written to the address once typing pauses; the kind writes at once.
 */
function TrashFilters({ search }: { search: TrashSearch }) {
  const { t } = useTranslation();
  const navigate = route.useNavigate();
  const searchId = useId();
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

  function commit(next: TrashSearch) {
    void navigate({ search: next, replace: true });
  }

  // A new filter opens its first page at the same size.
  function searchFor(text: string, kind: string | undefined): TrashSearch {
    const next: TrashSearch = keepSize(search);
    const known = TRASH_KINDS.find((each) => each === kind);
    if (known) next.kind = known;
    if (text.trim()) next.q = text.trim();
    return next;
  }

  function type(text: string) {
    setDraft(text);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => commit(searchFor(text, search.kind)), DEBOUNCE_MS);
  }

  function choose(kind: string) {
    clearTimeout(timer.current);
    commit(searchFor(draft, kind));
  }

  function clear() {
    clearTimeout(timer.current);
    setDraft("");
    commit(keepSize(search));
  }

  return (
    <FilterBar>
      <FilterField label={t("trash.search")} htmlFor={searchId} grow>
        <input
          id={searchId}
          type="search"
          value={draft}
          placeholder={t("trash.searchPlaceholder")}
          onChange={(event) => type(event.target.value)}
          className={filterControl}
        />
      </FilterField>
      <FilterField label={t("trash.columns.kind")} htmlFor={kindId}>
        <select
          id={kindId}
          value={search.kind ?? ""}
          onChange={(event) => choose(event.target.value)}
          className={`${filterControl} sm:w-44`}
        >
          <option value="">{t("trash.anyKind")}</option>
          {TRASH_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {t(kindKey(kind))}
            </option>
          ))}
        </select>
      </FilterField>
      {(search.kind !== undefined || search.q !== undefined || draft !== "") && (
        <button type="button" onClick={clear} className={filterButton}>
          {t("trash.clear")}
        </button>
      )}
    </FilterBar>
  );
}

type TableProps = { items: TrashedItem[]; feedback: Feedback; scrollKey: string };

function TrashTable({ items, feedback, scrollKey }: TableProps) {
  const { t, i18n } = useTranslation();
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });

  return (
    // A long name or detail scrolls the table inside its own box, never the page (9.10).
    <TableFrame scrollKey={scrollKey}>
      <table className={listTable}>
        <caption className="sr-only">{t("trash.title")}</caption>
        <thead className={listHead}>
          <tr>
            <th scope="col" className={listHeadCell}>
              {t("trash.columns.name")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("trash.columns.kind")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("trash.columns.detail")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("trash.columns.moved")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("trash.columns.actions")}
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <TrashRow
              key={`${item.kind}:${item.id}`}
              item={item}
              moved={date.format(new Date(item.trashed_at))}
              feedback={feedback}
            />
          ))}
        </tbody>
      </table>
    </TableFrame>
  );
}

type RowProps = { item: TrashedItem; moved: string; feedback: Feedback };

/** One record, with *Restore* and *Delete for good*, which asks in the row before it deletes. */
function TrashRow({ item, moved, feedback }: RowProps) {
  const { t } = useTranslation();
  const restore = useRestoreFromTrash({
    onDone: feedback.restored,
    onFailed: () => feedback.failed("restore"),
  });
  const remove = useDeleteForGood({ onFailed: () => feedback.failed("delete") });
  const [asking, setAsking] = useState(false);

  return (
    <tr className={`${listRow} align-top`}>
      <th scope="row" className={`${listCell} font-semibold`}>
        {item.name}
      </th>
      <td className={listCell}>{t(kindKey(item.kind))}</td>
      <td className={`${listCell} text-muted`}>{item.detail ?? ""}</td>
      <td className={`${listCell} text-muted`}>
        <time dateTime={item.trashed_at}>{moved}</time>
      </td>
      <td className={listCell}>
        {asking ? (
          <fieldset className="grid gap-2">
            <legend className="text-sm">{t("trash.deleteQuestion", { name: item.name })}</legend>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={remove.isPending}
                onClick={() => remove.mutate(item)}
                className="rounded-md bg-crit px-3 py-1 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
              >
                {t("trash.deleteConfirm")}
              </button>
              <button
                type="button"
                onClick={() => setAsking(false)}
                className="rounded-md border border-border-strong px-3 py-1 hover:bg-surface-2"
              >
                {t("trash.deleteCancel")}
              </button>
            </div>
          </fieldset>
        ) : (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={restore.isPending}
              aria-label={t("trash.restoreLabel", { name: item.name })}
              onClick={() => restore.mutate(item)}
              className="rounded-md border border-border-strong px-3 py-1 hover:bg-surface-2 disabled:opacity-60"
            >
              {t("trash.restore")}
            </button>
            <button
              type="button"
              aria-label={t("trash.deleteForGoodLabel", { name: item.name })}
              onClick={() => setAsking(true)}
              className="rounded-md border border-crit px-3 py-1 text-crit hover:bg-surface-2"
            >
              {t("trash.deleteForGood")}
            </button>
          </div>
        )}
      </td>
    </tr>
  );
}

/** Emptying asks first, in place: everything in the trash is gone for good once it goes. */
function EmptyTrash({ onEmptied }: { onEmptied: () => void }) {
  const { t } = useTranslation();
  const empty = useEmptyTrash(onEmptied);
  const [asking, setAsking] = useState(false);

  if (!asking) {
    return (
      <button
        type="button"
        onClick={() => setAsking(true)}
        className="inline-flex h-9 items-center rounded-md border border-crit px-3.5 text-sm text-crit hover:bg-surface-2"
      >
        {t("trash.emptyTrash")}
      </button>
    );
  }

  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm">{t("trash.emptyQuestion")}</legend>
      {empty.isError && (
        <p role="alert" className="text-sm text-crit">
          {t("trash.emptyError")}
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={empty.isPending}
          onClick={() => empty.mutate()}
          className="rounded-md bg-crit px-4 py-2 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {t("trash.emptyConfirm")}
        </button>
        <button
          type="button"
          onClick={() => setAsking(false)}
          className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
        >
          {t("trash.emptyCancel")}
        </button>
      </div>
    </fieldset>
  );
}

/** What a restore says: the record is back, and where to find it (requirement 9.4). */
function RestoredNotice({ item }: { item: TrashedItem }) {
  const { t } = useTranslation();

  return (
    <p className="flex flex-wrap items-baseline gap-x-2 rounded-lg border border-border bg-surface px-4 py-3 text-sm">
      <span>{t("trash.restored", { name: item.name })}</span>
      <RecordLink item={item} />
    </p>
  );
}

/** The restored record's own page, by its kind. */
function RecordLink({ item }: { item: TrashedItem }) {
  const { t } = useTranslation();
  const label = t("trash.open", { name: item.name });
  const className = "text-primary underline hover:opacity-80";

  switch (item.kind) {
    case "part":
      return (
        <Link to="/parts/$partId" params={{ partId: item.id }} className={className}>
          {label}
        </Link>
      );
    case "unit":
      return (
        <Link to="/units/$unitId" params={{ unitId: item.id }} className={className}>
          {label}
        </Link>
      );
    case "project":
      return (
        <Link to="/projects/$projectId" params={{ projectId: item.id }} className={className}>
          {label}
        </Link>
      );
    case "firmware":
      return (
        <Link to="/firmware/$firmwareId" params={{ firmwareId: item.id }} className={className}>
          {label}
        </Link>
      );
  }
}
