import { getRouteApi, Link } from "@tanstack/react-router";
import type { ProjectSummary } from "@wiredex/api-client";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { type ProjectSearch, revisionName, useProjects, useProjectTags } from "./projects";
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

  function searchFor(next: { q: string; tags: string[] }): ProjectSearch {
    const wanted: ProjectSearch = {};
    if (next.q.trim()) wanted.q = next.q.trim();
    if (next.tags.length > 0) wanted.tag = next.tags;
    return wanted;
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
  const narrowed = q !== "" || chosen.length > 0;

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
    <section className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-3xl font-semibold tracking-tight">
          {t("projects.list.title")}
        </h1>
        <Link
          to="/projects/new"
          className="rounded-md bg-primary px-4 py-2 font-semibold text-on-primary hover:opacity-90"
        >
          {t("projects.list.new")}
        </Link>
      </div>
      <p className="text-muted">{t("projects.list.intro")}</p>

      <div className="grid gap-3">
        <div className="grid max-w-md gap-1">
          <label htmlFor={searchId} className="text-sm font-medium">
            {t("projects.list.search")}
          </label>
          <input
            id={searchId}
            type="search"
            value={draft}
            placeholder={t("projects.list.searchPlaceholder")}
            onChange={(event) => type(event.target.value)}
            className="rounded-md border border-border-strong bg-surface px-3 py-2 text-text"
          />
        </div>
        {offered.length > 0 && (
          <fieldset className="flex flex-wrap items-center gap-2">
            <legend className="mb-1 w-full text-sm font-medium">{t("projects.list.tags")}</legend>
            {offered.map(({ tag, count }) => {
              const pressed = chosen.includes(tag);
              return (
                <button
                  key={tag}
                  type="button"
                  aria-pressed={pressed}
                  onClick={() => toggle(tag)}
                  className={`rounded-full border px-3 py-1 text-sm ${
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
      </div>

      {projects.isPending && <p className="text-muted">{t("projects.list.loading")}</p>}
      {projects.isError && (
        <p role="alert" className="text-crit">
          {t("projects.list.error")}
        </p>
      )}
      {projects.data && projects.data.length === 0 && (
        <div className="grid max-w-prose justify-items-start gap-3 rounded-lg border border-dashed border-border-strong bg-surface p-6">
          <p className="text-muted">
            {narrowed ? t("projects.list.noMatches") : t("projects.list.empty")}
          </p>
          {narrowed && (
            <button
              type="button"
              onClick={clear}
              className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
            >
              {t("projects.list.clear")}
            </button>
          )}
        </div>
      )}
      {projects.data && projects.data.length > 0 && <ProjectTable projects={projects.data} />}
    </section>
  );
}

function ProjectTable({ projects }: { projects: ProjectSummary[] }) {
  const { t, i18n } = useTranslation();
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });

  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{t("projects.list.title")}</caption>
        <thead className="border-b border-border text-muted">
          <tr>
            <th scope="col" className="px-4 py-2 font-medium">
              {t("projects.list.columns.name")}
            </th>
            <th scope="col" className="px-4 py-2 font-medium">
              {t("projects.list.columns.tags")}
            </th>
            <th scope="col" className="px-4 py-2 font-medium">
              {t("projects.list.columns.latest")}
            </th>
            <th scope="col" className="px-4 py-2 font-medium">
              {t("projects.list.columns.activity")}
            </th>
          </tr>
        </thead>
        <tbody>
          {projects.map((project) => {
            const latest = project.latest_revision;
            return (
              <tr key={project.id} className="border-b border-border last:border-b-0">
                <th scope="row" className="px-4 py-2 font-semibold">
                  <Link
                    to="/projects/$projectId"
                    params={{ projectId: project.id }}
                    className="hover:text-primary"
                  >
                    {project.name}
                  </Link>
                </th>
                <td className="px-4 py-2">
                  <span className="flex flex-wrap gap-1">
                    {project.tags.map((tag) => (
                      <span key={tag} className="rounded-full bg-surface-2 px-2 py-0.5 text-xs">
                        {tag}
                      </span>
                    ))}
                  </span>
                </td>
                <td className="px-4 py-2">
                  <span>{revisionName(t, latest)}</span>{" "}
                  <span className={statusTone[latest.status]}>{t(statusKey(latest.status))}</span>
                </td>
                <td className="px-4 py-2 text-muted">
                  <time dateTime={project.last_activity}>
                    {date.format(new Date(project.last_activity))}
                  </time>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
