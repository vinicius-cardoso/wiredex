import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChangeList } from "./ChangeList";
import { type TimelineKind, useTimeline } from "./history";

type Props = { kind: TimelineKind; recordId: string };

/**
 * A record's *History* (requirement 7.3): closed until *Show history*, so the page asks for
 * nothing more until then (decision 12), and once opened, the record's changes as the activity
 * page lists them, without naming the record the page already shows.
 */
export function HistorySection({ kind, recordId }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const headingId = useId();
  const listId = useId();
  const timeline = useTimeline(kind, recordId, open);
  const changes = timeline.data?.pages.flatMap((page) => page.changes) ?? [];

  return (
    <section aria-labelledby={headingId} className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id={headingId} className="font-display text-xl font-semibold">
          {t("history.section.title")}
        </h2>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => setOpen(!open)}
          className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
        >
          {open ? t("history.section.close") : t("history.section.open")}
        </button>
      </div>
      <div id={listId} hidden={!open}>
        {open && timeline.isPending && <p className="text-muted">{t("history.loading")}</p>}
        {open && timeline.isError && (
          <p role="alert" className="text-crit">
            {t("history.section.error")}
          </p>
        )}
        {open && timeline.isSuccess && (
          <ChangeList
            changes={changes}
            showRecord={false}
            hasMore={timeline.hasNextPage}
            loadingMore={timeline.isFetchingNextPage}
            onMore={() => void timeline.fetchNextPage()}
          />
        )}
      </div>
    </section>
  );
}
