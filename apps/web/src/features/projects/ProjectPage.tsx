import { Link, useNavigate } from "@tanstack/react-router";
import type { ProjectDetails } from "@wiredex/api-client";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { ProjectForm } from "./ProjectForm";
import {
  openRevision,
  ProjectRefusal,
  revisionName,
  useDeleteProject,
  useProject,
} from "./projects";
import { NewRevisionDialog } from "./RevisionDialogs";
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
 * *Revisions* navigation with the open one marked, and the open revision's panel. *Edit*
 * puts the project form in place of the header, *Delete* asks first, and *New revision* opens
 * its dialog.
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
  const navigate = useNavigate();
  const revisionsId = useId();
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const open = openRevision(project, revisionId);
  const latest = openRevision(project, undefined);

  return (
    <>
      {editing ? (
        <section className="grid gap-4">
          <h1 className="font-display text-3xl font-semibold tracking-tight">
            {t("projects.page.editTitle", { name: project.name })}
          </h1>
          <ProjectForm
            project={project}
            onSaved={() => setEditing(false)}
            onCancel={() => setEditing(false)}
          />
        </section>
      ) : (
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
          <div className="flex flex-wrap items-start gap-3">
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
            >
              {t("projects.page.edit")}
            </button>
            <DeleteProjectButton project={project} />
          </div>
        </header>
      )}

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
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="justify-self-start rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
          >
            {t("projects.page.newRevision")}
          </button>
        </nav>

        {open ? (
          // Keyed, so a dialog or a question open on one revision doesn't follow to the next.
          <RevisionPanel key={open.id} project={project} revision={open} />
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

      {adding && (
        <NewRevisionDialog
          project={project}
          onClose={() => setAdding(false)}
          onCreated={(revision) => {
            setAdding(false);
            void navigate({
              to: "/projects/$projectId/revisions/$revisionId",
              params: { projectId: project.id, revisionId: revision.id },
            });
          }}
        />
      )}
    </>
  );
}

/**
 * Deleting asks first: the project goes with every revision (requirement 1.7). A 409, a
 * revision that isn't a draft (1.8), shows the API's sentence beside the question.
 */
function DeleteProjectButton({ project }: { project: ProjectDetails }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const remove = useDeleteProject();
  const [asking, setAsking] = useState(false);

  if (!asking) {
    return (
      <button
        type="button"
        onClick={() => setAsking(true)}
        className="rounded-md border border-crit px-4 py-2 text-crit hover:bg-surface-2"
      >
        {t("projects.page.delete")}
      </button>
    );
  }

  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm">
        {t("projects.page.deleteQuestion", { name: project.name })}
      </legend>
      {remove.isError && (
        <p role="alert" className="text-sm text-crit">
          {(remove.error instanceof ProjectRefusal && remove.error.detail) ||
            t("projects.page.deleteError")}
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={remove.isPending}
          onClick={() =>
            remove.mutate(project.id, { onSuccess: () => void navigate({ to: "/projects" }) })
          }
          className="rounded-md bg-crit px-4 py-2 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {t("projects.page.deleteConfirm")}
        </button>
        <button
          type="button"
          onClick={() => setAsking(false)}
          className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
        >
          {t("projects.page.deleteCancel")}
        </button>
      </div>
    </fieldset>
  );
}
