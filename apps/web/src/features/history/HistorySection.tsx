import { useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Block, type BlockSpan } from "../../shared/ui/block";
import { useScrollToStart } from "../../shared/ui/list";
import {
  DEFAULT_PAGE_SIZE,
  type PageSize,
  Pagination,
  pageCount,
  useClampedPage,
} from "../../shared/ui/pagination";
import { ChangeList } from "./ChangeList";
import { type TimelineKind, useTimeline } from "./history";

type Props = { kind: TimelineKind; recordId: string; span?: BlockSpan | undefined };

/**
 * A record's *History* (requirement 7.3): closed until *Show history*, so the page asks for
 * nothing more until then (decision 12), and once opened, the record's changes as the activity
 * page lists them, without naming the record the page already shows. A block across the whole
 * row by default, at the end of the record's page grid; its changes stay in one column, as
 * they read best. Its page is its own, not the address's: the record's page already owns the
 * address, and the block opens closed.
 */
export function HistorySection({ kind, recordId, span = "full" }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState<PageSize>(DEFAULT_PAGE_SIZE);
  const listId = useId();
  const list = useRef<HTMLDivElement>(null);

  // Another record on the same page starts at its first page; adopted in render, as the
  // pages adopt the address, so there is no paint of the old page number.
  const shownFor = useRef(recordId);
  if (shownFor.current !== recordId) {
    shownFor.current = recordId;
    setPage(1);
  }

  const timeline = useTimeline(kind, recordId, open, page, size);
  const changes = timeline.data?.changes ?? [];
  useScrollToStart(list, `${page}:${size}`);
  useClampedPage(page, timeline.isPlaceholderData ? undefined : timeline.data?.page, setPage);

  return (
    <Block
      title={t("history.section.title")}
      span={span}
      actions={
        <button
          type="button"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => setOpen(!open)}
          className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
        >
          {open ? t("history.section.close") : t("history.section.open")}
        </button>
      }
    >
      <div id={listId} ref={list} hidden={!open}>
        {open && timeline.isPending && <p className="text-muted">{t("history.loading")}</p>}
        {open && timeline.isError && (
          <p role="alert" className="text-crit">
            {t("history.section.error")}
          </p>
        )}
        {open && timeline.isSuccess && (
          <div className="grid gap-3">
            <Pagination
              label={t("history.section.pages")}
              total={timeline.data.total}
              page={timeline.data.page}
              size={size}
              onChange={(next, nextSize) => {
                setPage(next);
                setSize(nextSize);
              }}
            />
            <ChangeList
              changes={changes}
              showRecord={false}
              atEnd={timeline.data.page >= pageCount(timeline.data.total, timeline.data.page_size)}
            />
          </div>
        )}
      </div>
    </Block>
  );
}
