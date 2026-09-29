import { Link, useNavigate } from "@tanstack/react-router";
import type { ProjectDetails, RevisionDetails } from "@wiredex/api-client";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { AttachmentsSection } from "../files/AttachmentsSection";
import { BomSection } from "./bom/BomSection";
import { LifecycleActions } from "./build/LifecycleActions";
import { ProjectRefusal, revisionName, useDeleteRevision } from "./projects";
import { EditRevisionDialog, ForkRevisionDialog } from "./RevisionDialogs";
import { statusKey, statusTone } from "./status";

type Props = { project: ProjectDetails; revision: RevisionDetails };

const action = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";

/**
 * One revision of a project (requirement 10.5): a region named by its heading, `Revision B –
 * perfboard`, with its status, the revision it was forked from, linking to it, and its notes
 * as written; *Edit*, *Fork* and *Delete*; its bill of materials; and the revision's files.
 */
export function RevisionPanel({ project, revision }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const headingId = useId();
  const [dialog, setDialog] = useState<"edit" | "fork" | null>(null);
  const source = project.revisions.find((sibling) => sibling.id === revision.forked_from);

  return (
    <section
      aria-labelledby={headingId}
      className="grid content-start gap-3 rounded-lg border border-border bg-surface p-4"
    >
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 id={headingId} className="font-display text-xl font-semibold">
          {t("projects.revision.heading", { name: revisionName(t, revision) })}
        </h2>
        <span
          className={`rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold ${statusTone[revision.status]}`}
        >
          {t(statusKey(revision.status))}
        </span>
      </div>

      <LifecycleActions revision={revision} />

      {source && (
        <p className="text-sm text-muted">
          {t("projects.revision.forkedFrom")}{" "}
          <Link
            to="/projects/$projectId/revisions/$revisionId"
            params={{ projectId: project.id, revisionId: source.id }}
            className="font-semibold text-primary hover:underline"
          >
            {source.label}
          </Link>
        </p>
      )}

      <div className="grid gap-1">
        <h3 className="text-sm font-semibold">{t("projects.revision.notes")}</h3>
        {revision.notes ? (
          <p className="whitespace-pre-line">{revision.notes}</p>
        ) : (
          <p className="text-sm text-muted">{t("projects.revision.noNotes")}</p>
        )}
      </div>

      <div className="flex flex-wrap items-start gap-2">
        <button type="button" onClick={() => setDialog("edit")} className={action}>
          {t("projects.revision.edit")}
        </button>
        <button type="button" onClick={() => setDialog("fork")} className={action}>
          {t("projects.revision.fork")}
        </button>
        <DeleteRevisionButton project={project} revision={revision} />
      </div>

      <BomSection revision={revision} />

      {/* A fork starts with no files: A's Gerbers document A (requirement 6.6). */}
      <AttachmentsSection owner={{ kind: "revision", id: revision.id }} />

      {dialog === "edit" && (
        <EditRevisionDialog revision={revision} onClose={() => setDialog(null)} />
      )}
      {dialog === "fork" && (
        <ForkRevisionDialog
          project={project}
          source={revision}
          onClose={() => setDialog(null)}
          onForked={(fork) => {
            setDialog(null);
            void navigate({
              to: "/projects/$projectId/revisions/$revisionId",
              params: { projectId: project.id, revisionId: fork.id },
            });
          }}
        />
      )}
    </section>
  );
}

/**
 * Deleting asks first. A project's only revision can't go (requirement 5.2), so its button
 * stays reachable but unavailable, the reason as its description, rather than vanishing.
 */
function DeleteRevisionButton({ project, revision }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const remove = useDeleteRevision();
  const reasonId = useId();
  const [asking, setAsking] = useState(false);
  const only = project.revisions.length <= 1;

  if (only) {
    return (
      <div className="grid gap-1">
        <button
          type="button"
          aria-disabled="true"
          aria-describedby={reasonId}
          className="cursor-not-allowed rounded-md border border-border px-3 py-1.5 text-sm text-muted"
        >
          {t("projects.revision.delete")}
        </button>
        <p id={reasonId} className="text-sm text-muted">
          {t("projects.revision.deleteOnly")}
        </p>
      </div>
    );
  }

  if (!asking) {
    return (
      <button
        type="button"
        onClick={() => setAsking(true)}
        className="rounded-md border border-crit px-3 py-1.5 text-sm text-crit hover:bg-surface-2"
      >
        {t("projects.revision.delete")}
      </button>
    );
  }

  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm">
        {t("projects.revision.deleteQuestion", { name: revisionName(t, revision) })}
      </legend>
      {remove.isError && (
        <p role="alert" className="text-sm text-crit">
          {(remove.error instanceof ProjectRefusal && remove.error.detail) ||
            t("projects.revision.deleteError")}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={remove.isPending}
          onClick={() =>
            remove.mutate(revision.id, {
              // The project's own address opens its latest revision (requirement 10.4).
              onSuccess: () =>
                void navigate({ to: "/projects/$projectId", params: { projectId: project.id } }),
            })
          }
          className="rounded-md bg-crit px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {t("projects.revision.deleteConfirm")}
        </button>
        <button type="button" onClick={() => setAsking(false)} className={action}>
          {t("projects.revision.deleteCancel")}
        </button>
      </div>
    </fieldset>
  );
}
