import { Link } from "@tanstack/react-router";
import type { HistoryChange, HistoryRecord, HistoryRowChange } from "@wiredex/api-client";
import type { TFunction } from "i18next";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { CollapseIcon, ExpandIcon, quietIconButton } from "../../shared/ui/icons";
import { RestoreRefusal, useRestoreVersion } from "./history";
import { actionKey, fieldKey, operationKey, recordKindKey, rowKindKey } from "./labels";
import { isLongValue, summarize } from "./summary";

type Props = {
  changes: HistoryChange[];
  /** The feed names each change's record; a record's own page doesn't need to. */
  showRecord: boolean;
  /** Whether this is the last page, where the note on where history starts belongs. */
  atEnd: boolean;
  /** Two columns of blocks on a wide screen, for a page that has the width to spare. */
  wide?: boolean;
  /** What an empty list says instead of "nothing has changed", when filters narrow it. */
  emptyText?: string;
};

/**
 * Changes, newest first (requirements 7.2, 7.3), each a block of the same height until it is
 * opened: what happened to which record, when, who, and one line of what changed. Opened, it
 * shows the rows it wrote with their fields before and after, and offers the restore when the
 * change can be restored. On the last page, where nothing older is left, a note says history
 * starts with this release (requirement 7.6).
 */
export function ChangeList({ changes, showRecord, atEnd, wide = false, emptyText }: Props) {
  const { t } = useTranslation();

  return (
    <div className="grid gap-3">
      {changes.length === 0 && <p className="text-muted">{emptyText ?? t("history.empty")}</p>}
      {changes.length > 0 && (
        <ol
          aria-label={t("history.list")}
          // Side by side on a wide screen; each block keeps its own height, so opening one
          // never stretches its neighbour.
          className={`grid gap-2 ${wide ? "xl:grid-cols-2 xl:items-start" : ""}`}
        >
          {changes.map((change) => (
            <ChangeBlock key={change.id} change={change} showRecord={showRecord} />
          ))}
        </ol>
      )}
      {(atEnd || changes.length === 0) && (
        <p className="text-sm text-muted">{t("history.start")}</p>
      )}
    </div>
  );
}

type BlockProps = {
  change: HistoryChange;
  showRecord: boolean;
  /** Whether the opened block offers the restore. The dashboard leaves that to the feed. */
  canRestore?: boolean;
};

/**
 * One change as a list item. Folded, every block is the same height: each line holds one line
 * of text and cuts what doesn't fit, a source file's text included. The icon button opens and
 * folds the detail, which is only drawn while open.
 */
export function ChangeBlock({ change, showRecord, canRestore = true }: BlockProps) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const detailId = useId();
  const toggle = open ? t("history.collapse") : t("history.expand");
  const when = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(change.occurred_at));

  return (
    // A container, so the lines follow the block's own width rather than the screen's: the
    // dashboard's narrow panel folds like a phone, the activity page like a laptop.
    <li className="@container min-w-0 rounded-lg border border-border bg-surface">
      <div className="flex items-start gap-2 py-2 pr-3 pl-1.5">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={detailId}
          aria-label={toggle}
          title={toggle}
          onClick={() => setOpen(!open)}
          className={quietIconButton}
        >
          {open ? <CollapseIcon /> : <ExpandIcon />}
        </button>
        {/* Three lines in a narrow block; two in a wide one, who and when beside the record. */}
        <div className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)] gap-x-3 text-sm leading-5 @lg:grid-cols-[minmax(0,1fr)_auto]">
          <p className="truncate">
            <span className="font-semibold">{t(actionKey(change.action))}</span>
            {showRecord && (
              <>
                {" "}
                <RecordName record={change.record} gone={change.action === "deleted"} />
              </>
            )}
          </p>
          <p className="truncate text-xs leading-5 text-muted @lg:col-start-2 @lg:row-start-1">
            <time dateTime={change.occurred_at}>{when}</time>{" "}
            {change.actor ? t("history.by", { name: change.actor }) : t("history.wiredex")}
          </p>
          <p className="truncate @lg:col-span-2">
            <Summary change={change} />
          </p>
        </div>
      </div>
      <div id={detailId} hidden={!open} className="border-t border-border px-3 py-2">
        {open && <ChangeDetail change={change} canRestore={canRestore} />}
      </div>
    </li>
  );
}

/** The folded block's second line (see `summarize`), in the reader's language. */
function Summary({ change }: { change: HistoryChange }) {
  const { t } = useTranslation();
  const summary = summarize(change);
  const empty = t("history.empty_value");

  switch (summary.type) {
    case "field": {
      const text = t("history.summary.field", {
        field: fieldName(t, summary.field.name),
        before: summary.field.before ?? empty,
        after: summary.field.after ?? empty,
      });
      return <>{inRow(t, summary.row, summary.own, text)}</>;
    }
    case "fields": {
      const text = t("history.summary.fields", {
        count: summary.fields.length,
        fields: summary.fields.map((field) => fieldName(t, field.name)).join(", "),
      });
      return <>{inRow(t, summary.row, summary.own, text)}</>;
    }
    case "row":
      return (
        <>
          {summary.row.operation === "insert"
            ? t("history.summary.added", { row: rowName(t, summary.row) })
            : t("history.summary.removed", { row: rowName(t, summary.row) })}
        </>
      );
    case "rows":
      return (
        <>
          {t("history.summary.rows", {
            count: summary.count,
            rows: summary.rows.map((row) => rowName(t, row)).join(", "),
          })}
        </>
      );
    case "nothing":
      return <span className="text-muted">{t("history.summary.nothing")}</span>;
  }
}

/** A change to what the record holds names the row it was made to; its own row needn't. */
function inRow(t: TFunction, row: HistoryRowChange, own: boolean, text: string): string {
  return own ? text : t("history.summary.inRow", { row: rowName(t, row), change: text });
}

/** A row as the feed names it: its kind, then its label when it has one. */
function rowName(t: TFunction, row: HistoryRowChange): string {
  const kind = t(rowKindKey(row.kind));
  return row.label ? `${kind} ${row.label}` : kind;
}

/** A field's word in the reader's language, or its own name when it has none. */
function fieldName(t: TFunction, name: string): string {
  const key = fieldKey(name);
  return key ? t(key) : name;
}

/** The opened block: every row the change wrote, how many more, and the restore. */
function ChangeDetail({ change, canRestore }: { change: HistoryChange; canRestore: boolean }) {
  const { t } = useTranslation();

  return (
    <div className="grid min-w-0 gap-2">
      {change.rows.length > 0 && (
        <ul className="grid gap-2">
          {change.rows.map((row, index) => (
            // Rows have no id of their own; their order within a change never moves.
            // biome-ignore lint/suspicious/noArrayIndexKey: the change's rows are a fixed list
            <RowItem key={index} row={row} />
          ))}
        </ul>
      )}
      {change.more_rows > 0 && (
        <p className="text-sm text-muted">{t("history.more", { count: change.more_rows })}</p>
      )}
      {canRestore && change.restorable && <RestoreControl change={change} />}
    </div>
  );
}

/**
 * The record a change is about, as it was named then, a link to its page while it has one. The
 * dashboard's recent activity names its records the same way (18-dashboard, requirement 3.1).
 */
export function RecordName({ record, gone }: { record: HistoryRecord; gone: boolean }) {
  const { t } = useTranslation();
  const label = record.label ?? t("history.unnamed");
  const kind = t(recordKindKey(record.kind));
  const className = "text-primary underline hover:opacity-80 wrap-anywhere";
  const text = `${kind} ${label}`;
  if (gone) return <span className="wrap-anywhere">{text}</span>;
  switch (record.kind) {
    case "part":
      return (
        <Link to="/parts/$partId" params={{ partId: record.id }} className={className}>
          {text}
        </Link>
      );
    case "unit":
      return (
        <Link to="/units/$unitId" params={{ unitId: record.id }} className={className}>
          {text}
        </Link>
      );
    case "project":
      return (
        <Link to="/projects/$projectId" params={{ projectId: record.id }} className={className}>
          {text}
        </Link>
      );
    case "firmware":
      return (
        <Link to="/firmware/$firmwareId" params={{ firmwareId: record.id }} className={className}>
          {text}
        </Link>
      );
    case "category":
      return (
        <Link to="/categories" className={className}>
          {text}
        </Link>
      );
    case "location":
      return (
        <Link to="/locations" className={className}>
          {text}
        </Link>
      );
  }
}

/** One row of a change: its kind, its name and what happened to it, then its fields. */
function RowItem({ row }: { row: HistoryRowChange }) {
  const { t } = useTranslation();

  return (
    <li className="grid min-w-0 gap-1 text-sm">
      <p className="wrap-anywhere">
        <span className="font-medium">{t(rowKindKey(row.kind))}</span>
        {row.label && <> {row.label}</>}{" "}
        <span className="text-muted">{t(operationKey(row.operation))}</span>
      </p>
      {row.fields.length > 0 && (
        <dl className="grid gap-1 border-l-2 border-border pl-3">
          {row.fields.map((field) => {
            const name = fieldName(t, field.name);
            const before = field.before ?? t("history.empty_value");
            const after = field.after ?? t("history.empty_value");
            const boxed = isLongValue(before) || isLongValue(after);
            return (
              <div key={field.name} className="grid min-w-0 gap-x-2 sm:grid-cols-[10rem_1fr]">
                <dt className="text-muted">{name}</dt>
                <dd className={`min-w-0 ${boxed ? "grid gap-1" : "wrap-anywhere"}`}>
                  {row.operation !== "insert" && (
                    <FieldValue text={before} field={name} side="before" boxed={boxed} />
                  )}
                  {row.operation === "update" && !boxed && <span aria-hidden="true"> → </span>}
                  {row.operation !== "delete" && (
                    <FieldValue text={after} field={name} side="after" boxed={boxed} />
                  )}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
    </li>
  );
}

type ValueProps = { text: string; field: string; side: "before" | "after"; boxed: boolean };

/**
 * A field's value, before or after. A long one, a source file's text say, keeps its line
 * breaks and scrolls inside its own box, never the page; the box takes focus, so the keyboard
 * can scroll it, and is named by its field and side.
 */
function FieldValue({ text, field, side, boxed }: ValueProps) {
  const { t } = useTranslation();
  const tone = side === "before" ? "text-muted line-through decoration-1" : "";
  if (!boxed) return <span className={tone}>{text}</span>;
  return (
    // biome-ignore lint/a11y/useSemanticElements: a fieldset groups form controls; this is a box of text.
    <div
      role="group"
      aria-label={t(`history.value.${side}`, { field })}
      // biome-ignore lint/a11y/noNoninteractiveTabindex: a box that scrolls must take focus for the keyboard to scroll it (WCAG 2.1.1).
      tabIndex={0}
      className={`max-h-40 overflow-auto rounded-md border border-border px-2 py-1 font-mono text-xs whitespace-pre-wrap wrap-anywhere ${tone}`}
    >
      {text}
    </div>
  );
}

/** *Restore the version before this change*, asking first in place (requirements 7.4, 7.5). */
function RestoreControl({ change }: { change: HistoryChange }) {
  const { t } = useTranslation();
  const restore = useRestoreVersion();
  const [asking, setAsking] = useState(false);
  const record = change.record.label ?? t(recordKindKey(change.record.kind));

  if (!asking) {
    return (
      <div className="grid gap-1">
        {restore.isSuccess && (
          <p role="status" className="text-sm text-ok">
            {t("history.restore.done")}
          </p>
        )}
        <button
          type="button"
          onClick={() => setAsking(true)}
          className="justify-self-start rounded-md border border-border-strong px-3 py-1 text-sm hover:bg-surface-2"
        >
          {t("history.restore.open")}
        </button>
      </div>
    );
  }

  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm">{t("history.restore.question", { record })}</legend>
      {restore.isError && (
        <p role="alert" className="text-sm text-crit wrap-anywhere">
          {restore.error instanceof RestoreRefusal && restore.error.detail
            ? t("history.restore.refused", { reason: restore.error.detail })
            : t("history.restore.failed")}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={restore.isPending}
          onClick={() => restore.mutate(change, { onSuccess: () => setAsking(false) })}
          className="rounded-md bg-primary px-3 py-1 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {t("history.restore.confirm")}
        </button>
        <button
          type="button"
          onClick={() => {
            restore.reset();
            setAsking(false);
          }}
          className="rounded-md border border-border-strong px-3 py-1 text-sm hover:bg-surface-2"
        >
          {t("history.restore.cancel")}
        </button>
      </div>
    </fieldset>
  );
}
