import { useTranslation } from "react-i18next";
import { ChangeList } from "./ChangeList";
import { useActivity } from "./history";

/** The workspace's activity (requirement 7.2): every change, newest first, 50 at a time. */
export function ActivityPage() {
  const { t } = useTranslation();
  const activity = useActivity();
  const changes = activity.data?.pages.flatMap((page) => page.changes) ?? [];

  return (
    <section className="grid max-w-4xl gap-4">
      <h1 className="font-display text-2xl font-semibold tracking-tight">{t("history.title")}</h1>
      <p className="max-w-prose text-muted">{t("history.intro")}</p>
      {activity.isPending && <p className="text-muted">{t("history.loading")}</p>}
      {activity.isError && (
        <p role="alert" className="text-crit">
          {t("history.error")}
        </p>
      )}
      {activity.isSuccess && (
        <ChangeList
          changes={changes}
          showRecord
          hasMore={activity.hasNextPage}
          loadingMore={activity.isFetchingNextPage}
          onMore={() => void activity.fetchNextPage()}
        />
      )}
    </section>
  );
}
