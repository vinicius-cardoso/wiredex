import { Link } from "@tanstack/react-router";
import type { RevisionRef } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { useRevisionRef } from "./lifecycle";

/**
 * A link to a revision, named by its project and its label: `Weather station · A – breadboard`.
 * It takes a ready `ref` where the answer already carries one (a part's holdings), and an `id`
 * otherwise (a unit's page), which {@link useRevisionRef} resolves — one request per revision,
 * shared through the query cache (requirements 13.8, 13.9). While the id is resolving the link
 * shows the revision's own id in a muted line, so the row never jumps.
 */
export function RevisionLink({ id }: { id: string }) {
  const ref = useRevisionRef(id);
  const { t } = useTranslation();
  if (!ref.data)
    return <span className="text-muted">{t("projects.holdings.loadingRevision")}</span>;
  return <RevisionRefLink revision={ref.data} />;
}

/** The link itself, over a ref the caller already holds. */
export function RevisionRefLink({ revision }: { revision: RevisionRef }) {
  const { t } = useTranslation();
  const label = revision.summary
    ? t("projects.revision.name", { label: revision.label, summary: revision.summary })
    : revision.label;
  return (
    <Link
      to="/projects/$projectId/revisions/$revisionId"
      params={{ projectId: revision.project_id, revisionId: revision.id }}
      className="text-primary hover:underline"
    >
      {t("projects.holdings.revisionName", { project: revision.project_name, revision: label })}
    </Link>
  );
}
