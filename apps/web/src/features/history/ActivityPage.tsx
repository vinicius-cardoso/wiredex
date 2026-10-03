import { useTranslation } from "react-i18next";
import { listPage, PageHeader } from "../../shared/ui/list";
import { ChangeList } from "./ChangeList";
import { useActivity } from "./history";

/**
 * The workspace's activity (requirement 7.2): every change, newest first, 50 at a time, each a
 * folded block. It takes the page's whole width, two columns of blocks on a wide screen, and on
 * a laptop the blocks scroll inside their own area under the header.
 */
export function ActivityPage() {
  const { t } = useTranslation();
  const activity = useActivity();
  const changes = activity.data?.pages.flatMap((page) => page.changes) ?? [];

  return (
    <section className={listPage}>
      <PageHeader title={t("history.title")} intro={t("history.intro")} />
      {activity.isPending && <p className="text-muted">{t("history.loading")}</p>}
      {activity.isError && (
        <p role="alert" className="text-crit">
          {t("history.error")}
        </p>
      )}
      {activity.isSuccess && (
        <div className="lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
          <ChangeList
            changes={changes}
            showRecord
            wide
            hasMore={activity.hasNextPage}
            loadingMore={activity.isFetchingNextPage}
            onMore={() => void activity.fetchNextPage()}
          />
        </div>
      )}
    </section>
  );
}
