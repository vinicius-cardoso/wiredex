import { getRouteApi, Link } from "@tanstack/react-router";
import type { ProjectSummary } from "@wiredex/api-client";
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
  type ProjectSearch,
  REVISION_STATUSES,
  revisionName,
  useProjects,
  useProjectTags,
} from "./projects";
import { statusKey, statusTone } from "./status";

/** How long typing pauses before the address, and so the list, changes. */
const DEBOUNCE_MS = 300;

const route = getRouteApi("/authenticated/projects");

/**
 * The projects list (requirement 10.2): a search box and the workspace's tags as toggles,
 * both kept in the address (`q`, `tag`), so a narrowed list can be bookmarked and walked with
 * Back. The box edits a draft that feels instant, written to the address once typing pauses;
 * a tag toggle writes at once. One row per project, freshest first, as the API orders them.
 */
export function ProjectsPage() {
  const { t } = useTranslation();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const searchId = useId();
  const statusId = useId();

  const q = search.q ?? "";
  const chosen = search.tag ?? [];
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

  function commit(next: ProjectSearch) {
    void navigate({ search: next, replace: true });
  }

  function searchFor(next: { q: string; tags: string[]; status?: string }): ProjectSearch {
    const wanted: ProjectSearch = {};
    if (next.q.trim()) wanted.q = next.q.trim();
    if (next.tags.length > 0) wanted.tag = next.tags;
    // The status rides along unless this change is the status itself.
    const status = REVISION_STATUSES.find(
      (known) => known === (next.status === undefined ? search.status : next.status),
    );
    if (status) wanted.status = status;
    return wanted;
  }

  function chooseStatus(value: string) {
    clearTimeout(timer.current);
    commit(searchFor({ q: draft, tags: chosen, status: value }));
  }

  function type(text: string) {
    setDraft(text);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => commit(searchFor({ q: text, tags: chosen })), DEBOUNCE_MS);
  }

  function toggle(tag: string) {
    const tags = chosen.includes(tag) ? chosen.filter((held) => held !== tag) : [...chosen, tag];
    clearTimeout(timer.current);
    commit(searchFor({ q: draft, tags }));
  }

  function clear() {
    clearTimeout(timer.current);
    setDraft("");
    commit({});
  }

  const projects = useProjects({ q, tags: chosen });
  const tags = useProjectTags();
  const narrowed = q !== "" || chosen.length > 0 || search.status !== undefined;
  // The name and tags are searched by the API; the status narrows what came back, by each
  // project's latest revision, which is the one the list shows.
  const shown = (projects.data ?? []).filter(
    (project) => !search.status || project.latest_revision.status === search.status,
  );

  // The workspace's tags, plus any the address asks for that no project carries any more, so
  // every active filter can still be switched off.
  const counted = tags.data ?? [];
  const offered = [
    ...counted.map((held) => ({ tag: held.tag, count: held.projects })),
    ...chosen
      .filter((tag) => !counted.some((held) => held.tag === tag))
      .map((tag) => ({ tag, count: 0 })),
  ];

  return (
    <section className={listPage}>
      <PageHeader
        title={t("projects.list.title")}
        intro={t("projects.list.intro")}
        actions={
          <Link to="/projects/new" className={primaryAction}>
            {t("projects.list.new")}
          </Link>
        }
      />
      <FilterBar>
        <FilterField label={t("projects.list.search")} htmlFor={searchId} grow>
          <input
            id={searchId}
            type="search"
            value={draft}
            placeholder={t("projects.list.searchPlaceholder")}
            onChange={(event) => type(event.target.value)}
            className={filterControl}
          />
        </FilterField>
        <FilterField label={t("projects.list.status")} htmlFor={statusId}>
          <select
            id={statusId}
            value={search.status ?? ""}
            onChange={(event) => chooseStatus(event.target.value)}
            className={`${filterControl} sm:w-44`}
          >
            <option value="">{t("projects.list.anyStatus")}</option>
            {REVISION_STATUSES.map((status) => (
              <option key={status} value={status}>
                {t(statusKey(status))}
              </option>
            ))}
          </select>
        </FilterField>
        {offered.length > 0 && (
          <fieldset className="flex min-w-0 flex-wrap items-center gap-1.5">
            <legend className="mb-1 text-xs font-medium text-muted">
              {t("projects.list.tags")}
            </legend>
            {offered.map(({ tag, count }) => {
              const pressed = chosen.includes(tag);
              return (
                <button
                  key={tag}
                  type="button"
                  aria-pressed={pressed}
                  onClick={() => toggle(tag)}
                  className={`h-9 rounded-full border px-3 text-sm ${
                    pressed
                      ? "border-primary bg-primary font-semibold text-on-primary"
                      : "border-border-strong hover:bg-surface-2"
                  }`}
                >
                  {t("projects.list.tagCount", { tag, count })}
                </button>
              );
            })}
          </fieldset>
        )}
        {narrowed && (
          <button type="button" onClick={clear} className={filterButton}>
            {t("projects.list.clear")}
          </button>
        )}
      </FilterBar>

      {projects.isPending && <p className="text-muted">{t("projects.list.loading")}</p>}
      {projects.isError && (
        <p role="alert" className="text-crit">
          {t("projects.list.error")}
        </p>
      )}
      {projects.data && shown.length === 0 && (
        <div className="grid max-w-prose justify-items-start gap-3 rounded-lg border border-dashed border-border-strong bg-surface p-6">
          <p className="text-muted">
            {narrowed ? t("projects.list.noMatches") : t("projects.list.empty")}
          </p>
        </div>
      )}
      {shown.length > 0 && <ProjectTable projects={shown} />}
    </section>
  );
}

function ProjectTable({ projects }: { projects: ProjectSummary[] }) {
  const { t, i18n } = useTranslation();
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });

  return (
    <TableFrame>
      <table className={listTable}>
        <caption className="sr-only">{t("projects.list.title")}</caption>
        <thead className={listHead}>
          <tr>
            <th scope="col" className={listHeadCell}>
              {t("projects.list.columns.name")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("projects.list.columns.tags")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("projects.list.columns.latest")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("projects.list.columns.activity")}
            </th>
          </tr>
        </thead>
        <tbody>
          {projects.map((project) => {
            const latest = project.latest_revision;
            return (
              <tr key={project.id} className={listRow}>
                <th scope="row" className={`${listCell} font-semibold`}>
                  <Link
                    to="/projects/$projectId"
                    params={{ projectId: project.id }}
                    className="hover:text-primary"
                  >
                    {project.name}
                  </Link>
                </th>
                <td className={listCell}>
                  <span className="flex flex-wrap gap-1">
                    {project.tags.map((tag) => (
                      <span key={tag} className="rounded-full bg-surface-2 px-2 py-0.5 text-xs">
                        {tag}
                      </span>
                    ))}
                  </span>
                </td>
                <td className={listCell}>
                  <span>{revisionName(t, latest)}</span>{" "}
                  <span className={statusTone[latest.status]}>{t(statusKey(latest.status))}</span>
                </td>
                <td className={`${listCell} text-muted`}>
                  <time dateTime={project.last_activity}>
                    {date.format(new Date(project.last_activity))}
                  </time>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </TableFrame>
  );
}
