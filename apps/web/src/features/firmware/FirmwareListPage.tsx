import { getRouteApi, Link } from "@tanstack/react-router";
import type { FirmwareSummary } from "@wiredex/api-client";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useFirmwareList } from "./firmware";
import { frameworkKey } from "./labels";

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

  function type(text: string) {
    setDraft(text);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      void navigate({ search: text.trim() ? { q: text.trim() } : {}, replace: true });
    }, DEBOUNCE_MS);
  }

  function clear() {
    clearTimeout(timer.current);
    setDraft("");
    void navigate({ search: {}, replace: true });
  }

  const firmware = useFirmwareList(q);

  return (
    <section className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-3xl font-semibold tracking-tight">
          {t("firmware.list.title")}
        </h1>
        <Link
          to="/firmware/new"
          className="rounded-md bg-primary px-4 py-2 font-semibold text-on-primary hover:opacity-90"
        >
          {t("firmware.list.new")}
        </Link>
      </div>
      <p className="text-muted">{t("firmware.list.intro")}</p>

      <div className="grid max-w-md gap-1">
        <label htmlFor={searchId} className="text-sm font-medium">
          {t("firmware.list.search")}
        </label>
        <input
          id={searchId}
          type="search"
          value={draft}
          placeholder={t("firmware.list.searchPlaceholder")}
          onChange={(event) => type(event.target.value)}
          className="rounded-md border border-border-strong bg-surface px-3 py-2 text-text"
        />
      </div>

      {firmware.isPending && <p className="text-muted">{t("firmware.list.loading")}</p>}
      {firmware.isError && (
        <p role="alert" className="text-crit">
          {t("firmware.list.error")}
        </p>
      )}
      {firmware.data && firmware.data.length === 0 && (
        <div className="grid max-w-prose justify-items-start gap-3 rounded-lg border border-dashed border-border-strong bg-surface p-6">
          <p className="text-muted">
            {q ? t("firmware.list.noMatches") : t("firmware.list.empty")}
          </p>
          {q && (
            <button
              type="button"
              onClick={clear}
              className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
            >
              {t("firmware.list.clear")}
            </button>
          )}
        </div>
      )}
      {firmware.data && firmware.data.length > 0 && <FirmwareTable firmware={firmware.data} />}
    </section>
  );
}

function FirmwareTable({ firmware }: { firmware: FirmwareSummary[] }) {
  const { t, i18n } = useTranslation();
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });

  return (
    // A long board target scrolls the table inside its own box, never the page (11.16).
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{t("firmware.list.title")}</caption>
        <thead className="border-b border-border text-muted">
          <tr>
            <th scope="col" className="px-4 py-2 font-medium">
              {t("firmware.list.columns.name")}
            </th>
            <th scope="col" className="px-4 py-2 font-medium">
              {t("firmware.list.columns.target")}
            </th>
            <th scope="col" className="px-4 py-2 font-medium">
              {t("firmware.list.columns.framework")}
            </th>
            <th scope="col" className="px-4 py-2 font-medium">
              {t("firmware.list.columns.latest")}
            </th>
            <th scope="col" className="px-4 py-2 font-medium">
              {t("firmware.list.columns.versions")}
            </th>
            <th scope="col" className="px-4 py-2 font-medium">
              {t("firmware.list.columns.changed")}
            </th>
          </tr>
        </thead>
        <tbody>
          {firmware.map((item) => (
            <tr key={item.id} className="border-b border-border last:border-b-0">
              <th scope="row" className="px-4 py-2 font-semibold">
                <Link
                  to="/firmware/$firmwareId"
                  params={{ firmwareId: item.id }}
                  className="hover:text-primary"
                >
                  {item.name}
                </Link>
              </th>
              <td className="px-4 py-2 font-mono text-xs">{item.target}</td>
              <td className="px-4 py-2">{t(frameworkKey(item.framework))}</td>
              <td className="px-4 py-2">
                {item.latest_release ? (
                  item.latest_release.version
                ) : (
                  <span className="text-muted">{t("firmware.list.noRelease")}</span>
                )}
              </td>
              <td className="px-4 py-2">
                <span className="block">
                  {t("firmware.list.versionCount", { count: item.versions })}
                </span>
                {item.drafts > 0 && (
                  <span className="block text-muted">
                    {t("firmware.list.draftCount", { count: item.drafts })}
                  </span>
                )}
              </td>
              <td className="px-4 py-2 text-muted">
                <time dateTime={item.updated_at}>{date.format(new Date(item.updated_at))}</time>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
