import { Link } from "@tanstack/react-router";
import type { ProjectDetails, RevisionDetails } from "@wiredex/api-client";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { revisionName } from "./projects";
import { statusKey, statusTone } from "./status";

type Props = { project: ProjectDetails; revision: RevisionDetails };

/**
 * One revision of a project (requirement 10.5): a region named by its heading, `Revision B –
 * perfboard`, with its status, the revision it was forked from, linking to it, and its notes
 * as written. 13 adds editing, forking and deleting; 14 the revision's files.
 */
export function RevisionPanel({ project, revision }: Props) {
  const { t } = useTranslation();
  const headingId = useId();
  const source = project.revisions.find((sibling) => sibling.id === revision.forked_from);

  return (
    <section
      aria-labelledby={headingId}
      className="grid gap-3 rounded-lg border border-border bg-surface p-4"
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
    </section>
  );
}
