import { Link } from "@tanstack/react-router";
import type { Flash, UnitFirmware, UnitResponse } from "@wiredex/api-client";
import { type RefObject, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { revisionName } from "../projects/projects";
import { FirmwareRefusal } from "./firmware";
import { useRemoveFlash, useUnitFirmware } from "./flashes";
import { LogFlashDialog } from "./LogFlashDialog";
import { refusalKey } from "./labels";

const action = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";
const cell = "px-2 py-1.5";

/**
 * What a board runs, on its unit's page (requirements 8.1, 8.4): a region named *Firmware*
 * with the current firmware and version as links, when it was flashed and a newer release in
 * words and an icon; *Log a flash*, or for a retired unit a line saying why there is none; then
 * the log, newest first, in a table that scrolls in its own box (8.11). The unit is the page's,
 * so a retire there shows here at once: its status decides *Log a flash*, and the revision
 * holding it the dialog's first group.
 */
export function FlashLogSection({ unit }: { unit: UnitResponse }) {
  const { t } = useTranslation();
  const headingId = useId();
  const log = useUnitFirmware(unit.id);
  const [logging, setLogging] = useState(false);

  return (
    <section aria-labelledby={headingId} className="grid min-w-0 gap-3">
      <h2 id={headingId} className="font-display text-xl font-semibold">
        {t("firmware.flash.title")}
      </h2>

      {/* Data first: a refetch that fails keeps showing what was loaded. */}
      {log.data ? (
        <Current log={log.data} />
      ) : log.isError ? (
        <p role="alert" className="text-crit">
          {t("firmware.flash.error")}
        </p>
      ) : (
        <p className="text-muted">{t("firmware.flash.loading")}</p>
      )}

      {unit.status === "retired" ? (
        <p className="text-sm text-muted">{t("firmware.flash.retired")}</p>
      ) : (
        <button
          type="button"
          onClick={() => setLogging(true)}
          className={`${action} justify-self-start`}
        >
          {t("firmware.flash.log")}
        </button>
      )}

      {log.data && log.data.flashes.length > 0 && <FlashTable log={log.data} />}

      {/* Here rather than beside the data, so a refetch never unmounts it before it settles. */}
      {logging && <LogFlashDialog unit={unit} onClose={() => setLogging(false)} />}
    </section>
  );
}

/** The version the newest flash wrote, or a line saying none is logged (requirement 2.2). */
function Current({ log }: { log: UnitFirmware }) {
  const { t } = useTranslation();
  const format = useTimeFormat();
  const { current, newer_release: newer } = log;
  if (!current) return <p className="text-muted">{t("firmware.flash.none")}</p>;

  return (
    <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-[auto_1fr]">
      <dt className="text-sm text-muted">{t("firmware.flash.firmware")}</dt>
      <dd className="min-w-0 break-words">
        <Link
          to="/firmware/$firmwareId"
          params={{ firmwareId: current.firmware_id }}
          className="font-semibold text-primary hover:underline"
        >
          {current.firmware_name}
        </Link>
      </dd>
      <dt className="text-sm text-muted">{t("firmware.flash.version")}</dt>
      <dd className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
        <Link
          to="/firmware/$firmwareId/versions/$versionId"
          params={{ firmwareId: current.firmware_id, versionId: current.version.id }}
          className="font-mono text-primary hover:underline"
        >
          {current.version.version}
        </Link>
        {/* A mismatch is --warn (decision 10), and says so in words beside its icon. */}
        {newer && (
          <Link
            to="/firmware/$firmwareId/versions/$versionId"
            params={{ firmwareId: current.firmware_id, versionId: newer.id }}
            className="text-sm font-semibold text-warn hover:underline"
          >
            <span aria-hidden="true">⚠ </span>
            {t("firmware.flash.newer", { version: newer.version })}
          </Link>
        )}
      </dd>
      <dt className="text-sm text-muted">{t("firmware.flash.flashedAt")}</dt>
      <dd>
        <time dateTime={current.flashed_at}>{format(current.flashed_at)}</time>
      </dd>
    </dl>
  );
}

function FlashTable({ log }: { log: UnitFirmware }) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">
          {t("firmware.flash.caption", { code: log.unit.code })}
        </caption>
        <thead>
          <tr className="border-b border-border text-muted">
            <th scope="col" className={`${cell} font-medium`}>
              {t("firmware.flash.columns.flashed")}
            </th>
            <th scope="col" className={`${cell} font-medium`}>
              {t("firmware.flash.columns.firmware")}
            </th>
            <th scope="col" className={`${cell} font-medium`}>
              {t("firmware.flash.columns.version")}
            </th>
            <th scope="col" className={`${cell} font-medium`}>
              {t("firmware.flash.columns.revision")}
            </th>
            <th scope="col" className={`${cell} font-medium`}>
              {t("firmware.flash.columns.notes")}
            </th>
            <th scope="col" className={cell}>
              <span className="sr-only">{t("firmware.flash.columns.actions")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {log.flashes.map((flash) => (
            <FlashRow key={flash.id} flash={flash} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * One entry: when, what and where it was flashed, and *Remove*, named by the entry so each
 * reads apart, which asks in its row first (requirement 8.5). Focus moves to *Keep it* when it
 * asks, and back to *Remove* when kept.
 */
function FlashRow({ flash }: { flash: Flash }) {
  const { t } = useTranslation();
  const format = useTimeFormat();
  const [asking, setAsking] = useState(false);
  const removeRef = useRef<HTMLButtonElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const [focusOn, setFocusOn] = useState<"remove" | "keep" | null>(null);
  const when = format(flash.flashed_at);

  useEffect(() => {
    if (!focusOn) return;
    ({ remove: removeRef, keep: keepRef })[focusOn].current?.focus();
    setFocusOn(null);
  }, [focusOn]);

  return (
    <tr className="border-b border-border align-top">
      <th scope="row" className={`${cell} font-normal whitespace-nowrap`}>
        <time dateTime={flash.flashed_at}>{when}</time>
      </th>
      <td className={`${cell} min-w-32 break-words`}>
        <Link
          to="/firmware/$firmwareId"
          params={{ firmwareId: flash.firmware_id }}
          className="text-primary hover:underline"
        >
          {flash.firmware_name}
        </Link>
      </td>
      <td className={cell}>
        <Link
          to="/firmware/$firmwareId/versions/$versionId"
          params={{ firmwareId: flash.firmware_id, versionId: flash.version.id }}
          className="font-mono text-primary hover:underline"
        >
          {flash.version.version}
        </Link>
      </td>
      <td className={`${cell} min-w-32 break-words`}>
        {flash.revision ? (
          <Link
            to="/projects/$projectId/revisions/$revisionId"
            params={{
              projectId: flash.revision.project_id,
              revisionId: flash.revision.revision_id,
            }}
            className="text-primary hover:underline"
          >
            {t("firmware.page.runsOnEntry", {
              project: flash.revision.project_name,
              revision: revisionName(t, flash.revision),
            })}
          </Link>
        ) : (
          <span className="text-muted">—</span>
        )}
      </td>
      <td className={`${cell} min-w-40 break-words`}>
        {flash.notes ?? <span className="text-muted">—</span>}
      </td>
      <td className={cell}>
        {asking ? (
          <RemoveQuestion
            flash={flash}
            keepRef={keepRef}
            onKeep={() => {
              setAsking(false);
              setFocusOn("remove");
            }}
          />
        ) : (
          <button
            ref={removeRef}
            type="button"
            aria-label={t("firmware.flash.removeEntry", {
              firmware: flash.firmware_name,
              version: flash.version.version,
              date: when,
            })}
            onClick={() => {
              setAsking(true);
              setFocusOn("keep");
            }}
            className={`${action} border-crit text-crit`}
          >
            {t("firmware.flash.remove")}
          </button>
        )}
      </td>
    </tr>
  );
}

type RemoveProps = {
  flash: Flash;
  keepRef: RefObject<HTMLButtonElement | null>;
  onKeep: () => void;
};

function RemoveQuestion({ flash, keepRef, onKeep }: RemoveProps) {
  const { t } = useTranslation();
  const remove = useRemoveFlash();
  const refusal = remove.error instanceof FirmwareRefusal ? remove.error : null;
  const key = refusalKey(refusal?.code ?? null);

  return (
    <div className="grid min-w-48 justify-items-start gap-1">
      <p>{t("firmware.flash.removeQuestion")}</p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={remove.isPending}
          onClick={() => remove.mutate(flash.id)}
          className={`${action} border-crit text-crit`}
        >
          {t("firmware.flash.removeConfirm")}
        </button>
        <button ref={keepRef} type="button" onClick={onKeep} className={action}>
          {t("firmware.flash.keep")}
        </button>
      </div>
      {remove.isError && (
        <p role="alert" className="text-crit">
          {key ? t(key, { item: refusal?.item ?? "" }) : t("firmware.flash.removeError")}
        </p>
      )}
    </div>
  );
}

/** An instant in the reader's language and zone, to the minute. */
function useTimeFormat(): (iso: string) => string {
  const { i18n } = useTranslation();
  const format = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  return (iso) => format.format(new Date(iso));
}
