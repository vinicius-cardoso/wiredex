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
import { type FirmwareSearch, releaseStates, useFirmwareList } from "./firmware";
import { FRAMEWORKS, frameworkKey } from "./labels";

/** How long typing pauses before the address, and so the list, changes. */
const DEBOUNCE_MS = 300;

const route = getRouteApi("/authenticated/firmware");

/**
 * The firmware list (requirement 11.2): a search box kept in the address (`q`), so a narrowed
 * list can be bookmarked and walked with Back. The box edits a draft that feels instant,
 * written to the address once typing pauses, as the projects list's is. One row per firmware,
 * last changed first, as the API orders them (requirement 2.2).
 */
export function FirmwareListPage() {
  const { t } = useTranslation();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const searchId = useId();
  const frameworkId = useId();
  const releaseId = useId();
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

  function commit(next: FirmwareSearch) {
    void navigate({ search: next, replace: true });
  }

  function type(text: string) {
    setDraft(text);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const { q: _gone, ...rest } = search;
      commit(text.trim() ? { ...rest, q: text.trim() } : rest);
    }, DEBOUNCE_MS);
  }

  /** A select's choice goes to the address at once; its empty option drops the filter. */
  function choose(key: "framework" | "release", value: string) {
    clearTimeout(timer.current);
    const next: FirmwareSearch = {};
    if (draft.trim()) next.q = draft.trim();
    const framework = key === "framework" ? value : search.framework;
    const release = key === "release" ? value : search.release;
    const knownFramework = FRAMEWORKS.find((known) => known === framework);
    const knownRelease = releaseStates.find((known) => known === release);
    if (knownFramework) next.framework = knownFramework;
    if (knownRelease) next.release = knownRelease;
    commit(next);
  }

  function clear() {
    clearTimeout(timer.current);
    setDraft("");
    commit({});
  }

  const firmware = useFirmwareList(q);
  // The name and board are searched by the API; the two selects narrow what came back.
  const shown = (firmware.data ?? []).filter(
    (item) =>
      (!search.framework || item.framework === search.framework) &&
      (!search.release || (item.latest_release !== null) === (search.release === "released")),
  );
  const narrowed = q !== "" || search.framework !== undefined || search.release !== undefined;

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
            onChange={(event) => type(event.target.value)}
            className={filterControl}
          />
        </FilterField>
        <FilterField label={t("firmware.list.columns.framework")} htmlFor={frameworkId}>
          <select
            id={frameworkId}
            value={search.framework ?? ""}
            onChange={(event) => choose("framework", event.target.value)}
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
            onChange={(event) => choose("release", event.target.value)}
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
      {shown.length > 0 && <FirmwareTable firmware={shown} />}
    </section>
  );
}

function FirmwareTable({ firmware }: { firmware: FirmwareSummary[] }) {
  const { t, i18n } = useTranslation();
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });

  return (
    // A long board target scrolls the table inside its own box, never the page (11.16).
    <TableFrame>
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
