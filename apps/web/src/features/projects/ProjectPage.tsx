import { Link } from "@tanstack/react-router";
import type { ProjectDetails } from "@wiredex/api-client";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { openRevision, revisionName, useProject } from "./projects";
import { RevisionPanel } from "./RevisionPanel";
import { statusKey } from "./status";

type Props = {
  projectId: string;
  /** The revision the address names; absent means the latest (requirement 10.4). */
  revisionId?: string;
};

/**
 * A project's page, at `/projects/$projectId` and `/projects/$projectId/revisions/$revisionId`:
 * the header (name, tags linking to the filtered list, the description as written), the
 * *Revisions* navigation with the open one marked, and the open revision's panel.
 */
export function ProjectPage({ projectId, revisionId }: Props) {
  const { t } = useTranslation();
  const project = useProject(projectId);

  return (
    <section className="grid gap-6">
      <Link to="/projects" className="text-sm text-muted hover:text-primary">
        {t("projects.page.back")}
      </Link>
      {project.isPending && <p className="text-muted">{t("projects.page.loading")}</p>}
      {project.isError && (
        <p role="alert" className="text-crit">
          {t("projects.page.error")}
        </p>
      )}
      {project.data && <ProjectDetail project={project.data} revisionId={revisionId} />}
    </section>
  );
}

function ProjectDetail({
  project,
  revisionId,
}: {
  project: ProjectDetails;
  revisionId: string | undefined;
}) {
  const { t } = useTranslation();
  const revisionsId = useId();
  const open = openRevision(project, revisionId);
  const latest = openRevision(project, undefined);

  return (
    <>
      <header className="grid gap-3">
        <h1 className="font-display text-3xl font-semibold tracking-tight">{project.name}</h1>
        {project.tags.length > 0 && (
          <ul aria-label={t("projects.page.tags")} className="flex flex-wrap gap-2">
            {project.tags.map((tag) => (
              <li key={tag}>
                <Link
                  to="/projects"
                  search={{ tag: [tag] }}
                  className="rounded-full bg-surface-2 px-2.5 py-0.5 text-sm hover:text-primary"
                >
                  {tag}
                </Link>
              </li>
            ))}
          </ul>
        )}
        {project.description && (
          <p className="max-w-prose whitespace-pre-line">{project.description}</p>
        )}
      </header>

      <div className="grid gap-4 md:grid-cols-[14rem_1fr]">
        <nav aria-labelledby={revisionsId} className="grid content-start gap-2">
          <h2 id={revisionsId} className="text-sm font-semibold text-muted">
            {t("projects.page.revisions")}
          </h2>
          <ul className="grid gap-1">
            {project.revisions.map((revision) => {
              const current = revision.id === open?.id;
              return (
                <li key={revision.id}>
                  <Link
                    to="/projects/$projectId/revisions/$revisionId"
                    params={{ projectId: project.id, revisionId: revision.id }}
                    // Set here rather than left to the router: the project's own address
                    // opens the latest revision, whose link the router doesn't see as active.
                    aria-current={current ? "page" : undefined}
                    activeProps={{}}
                    className={`block rounded-md px-3 py-1.5 text-sm hover:bg-surface-2 ${
                      current ? "bg-surface-2 font-semibold text-primary" : ""
                    }`}
                  >
                    {t("projects.page.revisionEntry", {
                      name: revisionName(t, revision),
                      status: t(statusKey(revision.status)),
                    })}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        {open ? (
          <RevisionPanel project={project} revision={open} />
        ) : (
          <div
            role="alert"
            className="grid content-start justify-items-start gap-2 rounded-lg border border-dashed border-border-strong bg-surface p-6"
          >
            <p>{t("projects.page.noSuchRevision")}</p>
            {latest && (
              <Link
                to="/projects/$projectId/revisions/$revisionId"
                params={{ projectId: project.id, revisionId: latest.id }}
                className="font-semibold text-primary hover:underline"
              >
                {t("projects.page.openLatest", { name: revisionName(t, latest) })}
              </Link>
            )}
          </div>
        )}
      </div>
    </>
  );
}
