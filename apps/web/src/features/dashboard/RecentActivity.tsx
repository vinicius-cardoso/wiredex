import type { UseQueryResult } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import type { HistoryPage } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { ChangeBlock } from "../history/ChangeList";
import { Panel, PanelStates } from "./Panel";

/**
 * The workspace's newest changes as 17's feed answers them (requirement 3.1), folded as the
 * activity page folds them: what happened to which record, linking to it, who, when and one
 * line of what changed. Opened, a change shows its rows and fields; restoring a version stays on
 * the activity page this links to (requirement 3.2).
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
            <ChangeBlock key={change.id} change={change} showRecord canRestore={false} />
          ))}
        </ol>
      )}
    </Panel>
  );
}
