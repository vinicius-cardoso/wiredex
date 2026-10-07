import { getRouteApi, Link } from "@tanstack/react-router";
import type { FirmwareSummary } from "@wiredex/api-client";
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
  primaryAction,
  TableFrame,
} from "../../shared/ui/list";
import {
  keepSize,
  Pagination,
  pageOfSearch,
  slicePage,
  useClampedPage,
  withPage,
} from "../../shared/ui/pagination";
import { type FirmwareSearch, releaseStates, targetMatches, useFirmwareList } from "./firmware";
import { FRAMEWORKS, frameworkKey } from "./labels";

/** How long typing pauses before the address, and so the list, changes. */
const DEBOUNCE_MS = 300;

const route = getRouteApi("/authenticated/firmware");

/** What one filter change sets; the rest of the search rides along as it is. */
type Change = { q?: string; target?: string; framework?: string; release?: string };

/**
 * The firmware list (requirement 11.2): a search box, a board target box and two selects, all
 * kept in the address (`q`, `target`, `framework`, `release`), so a narrowed list can be
 * bookmarked and walked with Back. Each box edits a draft that feels instant, written to the
 * address once typing pauses, as the projects list's is; a select writes at once. One row per
 * firmware, last changed first, as the API orders them (requirement 2.2). The API answers the
 * list whole, so it is paged here, after the filters, with the page and size in the address
 * too (`page`, `size`); a new filter starts again at page 1.
 */
export function FirmwareListPage() {
  const { t } = useTranslation();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const searchId = useId();
  const targetId = useId();
  const frameworkId = useId();
  const releaseId = useId();
  const q = search.q ?? "";
  const target = search.target ?? "";
  const { page, size } = pageOfSearch(search);

  const [draft, setDraft] = useState(q);
  const [targetDraft, setTargetDraft] = useState(target);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Back, Forward or a shared link change the address without touching the drafts; adopt the
  // address's text then, in render rather than an effect, so there is no extra paint.
  const lastQ = useRef(q);
  if (lastQ.current !== q) {
    lastQ.current = q;
    setDraft(q);
  }
  const lastTarget = useRef(target);
  if (lastTarget.current !== target) {
    lastTarget.current = target;
    setTargetDraft(target);
  }

  useEffect(() => () => clearTimeout(timer.current), []);

  function commit(next: FirmwareSearch) {
    void navigate({ search: next, replace: true });
  }

  /** The address for the filters, the one being changed taken from `change`. */
  function searchFor(change: Change): FirmwareSearch {
    // A new filter starts again at page 1, at the size chosen.
    const next: FirmwareSearch = keepSize(search);
    const text = (change.q ?? draft).trim();
    if (text) next.q = text;
    const board = (change.target ?? targetDraft).trim();
    if (board) next.target = board;
    const framework = FRAMEWORKS.find((known) => known === (change.framework ?? search.framework));
    if (framework) next.framework = framework;
    const release = releaseStates.find((known) => known === (change.release ?? search.release));
    if (release) next.release = release;
    return next;
  }

  /** A box's text goes to the address once typing pauses. */
  function type(change: { q: string } | { target: string }) {
    if ("q" in change) setDraft(change.q);
    else setTargetDraft(change.target);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => commit(searchFor(change)), DEBOUNCE_MS);
  }

  /** A select's choice goes to the address at once; its empty option drops the filter. */
  function choose(change: { framework: string } | { release: string }) {
    clearTimeout(timer.current);
    commit(searchFor(change));
  }

  function clear() {
    clearTimeout(timer.current);
    setDraft("");
    setTargetDraft("");
    commit(keepSize(search));
  }

  const firmware = useFirmwareList(q);
  // The name and board are searched by the API; the board target box and the two selects
  // narrow what came back, which is the whole list.
  const shown = (firmware.data ?? []).filter(
    (item) =>
      (!target || targetMatches(item.target, target)) &&
      (!search.framework || item.framework === search.framework) &&
      (!search.release || (item.latest_release !== null) === (search.release === "released")),
  );
  const narrowed =
    q !== "" || target !== "" || search.framework !== undefined || search.release !== undefined;
  const paged = slicePage(shown, page, size);
  // A page past the end opens the last one, and the address says so. Rows kept on screen
  // from the previous search don't count: they would clamp to a page this search may not have.
  useClampedPage(
    page,
    firmware.data && !firmware.isPlaceholderData ? paged.page : undefined,
    (served) => void navigate({ search: (prev) => withPage(prev, served, size), replace: true }),
  );

  return (
    <section className={listPage}>
      <PageHeader
        title={t("firmware.list.title")}
        intro={t("firmware.list.intro")}
        actions={
          <Link to="/firmware/new" className={primaryAction}>
            {t("firmware.list.new")}
          </Link>
        }
      />
      <FilterBar>
        <FilterField label={t("firmware.list.search")} htmlFor={searchId} grow>
          <input
            id={searchId}
            type="search"
            value={draft}
            placeholder={t("firmware.list.searchPlaceholder")}
            onChange={(event) => type({ q: event.target.value })}
            className={filterControl}
          />
        </FilterField>
        <FilterField label={t("firmware.list.columns.target")} htmlFor={targetId}>
          <input
            id={targetId}
            type="text"
            value={targetDraft}
            placeholder={t("firmware.list.targetPlaceholder")}
            onChange={(event) => type({ target: event.target.value })}
            className={`${filterControl} font-mono sm:w-52`}
          />
        </FilterField>
        <FilterField label={t("firmware.list.columns.framework")} htmlFor={frameworkId}>
          <select
            id={frameworkId}
            value={search.framework ?? ""}
            onChange={(event) => choose({ framework: event.target.value })}
            className={`${filterControl} sm:w-44`}
          >
            <option value="">{t("firmware.list.anyFramework")}</option>
            {FRAMEWORKS.map((framework) => (
              <option key={framework} value={framework}>
                {t(frameworkKey(framework))}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label={t("firmware.list.release")} htmlFor={releaseId}>
          <select
            id={releaseId}
            value={search.release ?? ""}
            onChange={(event) => choose({ release: event.target.value })}
            className={`${filterControl} sm:w-44`}
          >
            <option value="">{t("firmware.list.anyRelease")}</option>
            {releaseStates.map((state) => (
              <option key={state} value={state}>
                {t(`firmware.list.releaseStates.${state}`)}
              </option>
            ))}
          </select>
        </FilterField>
        {narrowed && (
          <button type="button" onClick={clear} className={filterButton}>
            {t("firmware.list.clear")}
          </button>
        )}
      </FilterBar>

      <Pagination
        label={t("firmware.list.pages")}
        total={paged.total}
        page={paged.page}
        size={size}
        onChange={(next, nextSize) =>
          void navigate({ search: (prev) => withPage(prev, next, nextSize) })
        }
      />
      {firmware.isPending && <p className="text-muted">{t("firmware.list.loading")}</p>}
      {firmware.isError && (
        <p role="alert" className="text-crit">
          {t("firmware.list.error")}
        </p>
      )}
      {firmware.data && shown.length === 0 && (
        <div className="grid max-w-prose justify-items-start gap-3 rounded-lg border border-dashed border-border-strong bg-surface p-6">
          <p className="text-muted">
            {narrowed ? t("firmware.list.noMatches") : t("firmware.list.empty")}
          </p>
        </div>
      )}
      {shown.length > 0 && <FirmwareTable firmware={paged.items} scrollKey={`${page}:${size}`} />}
    </section>
  );
}

function FirmwareTable({
  firmware,
  scrollKey,
}: {
  firmware: FirmwareSummary[];
  scrollKey: string;
}) {
  const { t, i18n } = useTranslation();
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });

  return (
    // A long board target scrolls the table inside its own box, never the page (11.16).
    <TableFrame scrollKey={scrollKey}>
      <table className={listTable}>
        <caption className="sr-only">{t("firmware.list.title")}</caption>
        <thead className={listHead}>
          <tr>
            <th scope="col" className={listHeadCell}>
              {t("firmware.list.columns.name")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("firmware.list.columns.target")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("firmware.list.columns.framework")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("firmware.list.columns.latest")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("firmware.list.columns.versions")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("firmware.list.columns.changed")}
            </th>
          </tr>
        </thead>
        <tbody>
          {firmware.map((item) => (
            <tr key={item.id} className={listRow}>
              <th scope="row" className={`${listCell} font-semibold`}>
                <Link
                  to="/firmware/$firmwareId"
                  params={{ firmwareId: item.id }}
                  className="hover:text-primary"
                >
                  {item.name}
                </Link>
              </th>
              <td className={`${listCell} font-mono text-xs`}>{item.target}</td>
              <td className={listCell}>{t(frameworkKey(item.framework))}</td>
              <td className={listCell}>
                {item.latest_release ? (
                  item.latest_release.version
                ) : (
                  <span className="text-muted">{t("firmware.list.noRelease")}</span>
                )}
              </td>
              <td className={listCell}>
                <span className="block">
                  {t("firmware.list.versionCount", { count: item.versions })}
                </span>
                {item.drafts > 0 && (
                  <span className="block text-muted">
                    {t("firmware.list.draftCount", { count: item.drafts })}
                  </span>
                )}
              </td>
              <td className={`${listCell} text-muted`}>
                <time dateTime={item.updated_at}>{date.format(new Date(item.updated_at))}</time>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableFrame>
  );
}
