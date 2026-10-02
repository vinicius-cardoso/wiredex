import { Link } from "@tanstack/react-router";
import type { HistoryChange, HistoryRecord, HistoryRowChange } from "@wiredex/api-client";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { RestoreRefusal, useRestoreVersion } from "./history";
import { actionKey, fieldKey, operationKey, recordKindKey, rowKindKey } from "./labels";

type Props = {
  changes: HistoryChange[];
  /** The feed names each change's record; a record's own page doesn't need to. */
  showRecord: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  onMore: () => void;
};

/**
 * Changes, newest first (requirements 7.2, 7.3): when, who, what happened to which record, and
 * the rows it wrote with their fields before and after. A change that can be restored offers it,
 * asking in place. Once nothing older is left, a note says history starts with this release
 * (requirement 7.6).
 */
export function ChangeList({ changes, showRecord, hasMore, loadingMore, onMore }: Props) {
  const { t } = useTranslation();

  return (
    <div className="grid gap-3">
      {changes.length === 0 && <p className="text-muted">{t("history.empty")}</p>}
      {changes.length > 0 && (
        <ol aria-label={t("history.list")} className="grid gap-3">
          {changes.map((change) => (
            <ChangeItem key={change.id} change={change} showRecord={showRecord} />
          ))}
        </ol>
      )}
      {hasMore ? (
        <button
          type="button"
          onClick={onMore}
          disabled={loadingMore}
          className="justify-self-start rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2 disabled:opacity-60"
        >
          {t("history.showMore")}
        </button>
      ) : (
        <p className="text-sm text-muted">{t("history.start")}</p>
      )}
    </div>
  );
}

function ChangeItem({ change, showRecord }: { change: HistoryChange; showRecord: boolean }) {
  const { t, i18n } = useTranslation();
  const when = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(change.occurred_at));

  return (
    <li className="grid min-w-0 gap-2 rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-semibold">{t(actionKey(change.action))}</span>
        {showRecord && <RecordName record={change.record} gone={change.action === "deleted"} />}
        <span className="text-sm text-muted">
          <time dateTime={change.occurred_at}>{when}</time>{" "}
          {change.actor ? t("history.by", { name: change.actor }) : t("history.wiredex")}
        </span>
      </div>
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
      {change.restorable && <RestoreControl change={change} />}
    </li>
  );
}

/** The record a change is about, as it was named then, a link to its page while it has one. */
function RecordName({ record, gone }: { record: HistoryRecord; gone: boolean }) {
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
          {row.fields.map((field) => (
            <div key={field.name} className="grid min-w-0 gap-x-2 sm:grid-cols-[10rem_1fr]">
              <dt className="text-muted">
                <FieldName name={field.name} />
              </dt>
              <dd className="min-w-0 wrap-anywhere">
                {row.operation !== "insert" && (
                  <span className="text-muted line-through decoration-1">
                    {field.before ?? t("history.empty_value")}
                  </span>
                )}
                {row.operation === "update" && <span aria-hidden="true"> → </span>}
                {row.operation !== "delete" && (
                  <span>{field.after ?? t("history.empty_value")}</span>
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </li>
  );
}

/** A field's word in the reader's language, or its own name when it has none. */
function FieldName({ name }: { name: string }) {
  const { t } = useTranslation();
  const key = fieldKey(name);
  return <>{key ? t(key) : name}</>;
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
