import type { UseQueryResult } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import type { HistoryChange, HistoryPage } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { RecordName } from "../history/ChangeList";
import { actionKey } from "../history/labels";
import { Panel, PanelStates } from "./Panel";

/**
 * The workspace's newest changes as 17's feed answers them (requirement 3.1): what happened to
 * which record, linking to it, who and when. The rows and fields, and restoring a version, stay
 * on the activity page this links to (requirement 3.2).
 */
export function RecentActivityPanel({ query }: { query: UseQueryResult<HistoryPage> }) {
  const { t } = useTranslation();
  const changes = query.data?.changes ?? [];

  return (
    <Panel
      title={t("dashboard.activity.title")}
      action={
        <Link to="/activity" className="text-sm text-primary hover:underline">
          {t("dashboard.activity.all")}
        </Link>
      }
    >
      <PanelStates
        query={query}
        loading={t("dashboard.activity.loading")}
        error={t("dashboard.activity.error")}
        empty={changes.length === 0 ? t("history.empty") : null}
      />
      {changes.length > 0 && (
        <ol aria-label={t("dashboard.activity.list")} className="grid gap-2">
          {changes.map((change) => (
            <RecentChange key={change.id} change={change} />
          ))}
        </ol>
      )}
    </Panel>
  );
}

function RecentChange({ change }: { change: HistoryChange }) {
  const { t, i18n } = useTranslation();
  const when = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(change.occurred_at));

  return (
    <li className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b border-border pb-2 text-sm last:border-b-0">
      <span className="font-semibold">{t(actionKey(change.action))}</span>
      <RecordName record={change.record} gone={change.action === "deleted"} />
      <span className="text-muted">
        <time dateTime={change.occurred_at}>{when}</time>{" "}
        {change.actor ? t("history.by", { name: change.actor }) : t("history.wiredex")}
      </span>
    </li>
  );
}
