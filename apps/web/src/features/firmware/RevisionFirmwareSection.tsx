import { Link } from "@tanstack/react-router";
import type { FirmwareSummary } from "@wiredex/api-client";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useFirmwareList,
  useLinkRevision,
  useRevisionFirmware,
  useUnlinkRevision,
} from "./firmware";

const action = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";

/**
 * The firmware a revision runs, in its panel after the wiring (requirement 11.11): a region
 * named by its heading, each firmware a link to its page with its latest release and *Unlink*,
 * then a select of the workspace's other firmware with *Link*, and *New firmware*, which
 * starts one running on this revision. A link is made whatever the revision's status
 * (decision 2), so nothing here locks the way the BOM and the wiring do.
 */
export function RevisionFirmwareSection({ revisionId }: { revisionId: string }) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const selectId = useId();
  const running = useRevisionFirmware(revisionId);
  const workspace = useFirmwareList("");
  // Here rather than in the form, which goes once the last firmware on offer is linked.
  const link = useLinkRevision();
  const [chosen, setChosen] = useState("");
  const linked = new Set((running.data ?? []).map((firmware) => firmware.id));
  const others = (workspace.data ?? [])
    .filter((firmware) => !linked.has(firmware.id))
    .sort((a, b) => a.name.localeCompare(b.name, i18n.language));
  // The one chosen while it is still on offer, else the first: a link takes it off the list.
  const selected = others.find((firmware) => firmware.id === chosen) ?? others[0];

  function onLink(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected) link.mutate({ firmwareId: selected.id, revisionId });
  }

  return (
    <section aria-labelledby={headingId} className="grid min-w-0 gap-3">
      <h3 id={headingId} className="font-display text-xl font-semibold">
        {t("firmware.revision.title")}
      </h3>

      {running.isPending && <p className="text-muted">{t("firmware.revision.loading")}</p>}
      {running.isError && (
        <p role="alert" className="text-crit">
          {t("firmware.revision.error")}
        </p>
      )}

      {running.data?.length === 0 && <p className="text-muted">{t("firmware.revision.empty")}</p>}
      {running.data && running.data.length > 0 && (
        <ul className="grid gap-2">
          {running.data.map((firmware) => (
            <RunningFirmware key={firmware.id} firmware={firmware} revisionId={revisionId} />
          ))}
        </ul>
      )}

      {running.data && selected && (
        <form onSubmit={onLink} className="flex flex-wrap items-end gap-2">
          <div className="grid min-w-0 gap-1">
            <label htmlFor={selectId} className="text-sm font-semibold">
              {t("firmware.revision.choose")}
            </label>
            <select
              id={selectId}
              value={selected.id}
              onChange={(event) => setChosen(event.target.value)}
              className="max-w-full rounded-md border border-border-strong bg-surface px-3 py-1.5 text-sm text-text"
            >
              {others.map((firmware) => (
                <option key={firmware.id} value={firmware.id}>
                  {firmware.name}
                </option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            disabled={link.isPending}
            className={`${action} disabled:opacity-60`}
          >
            {t("firmware.revision.link")}
          </button>
        </form>
      )}
      {link.isError && (
        <p role="alert" className="text-sm text-crit">
          {t("firmware.revision.linkError")}
        </p>
      )}

      <Link
        to="/firmware/new"
        search={{ revision: revisionId }}
        className={`${action} justify-self-start`}
      >
        {t("firmware.revision.new")}
      </Link>
    </section>
  );
}

/**
 * One firmware the revision runs: a link to its page, its latest release, and *Unlink*, named
 * by the firmware so each reads apart. Unlinking asks nothing: linking again undoes it.
 */
function RunningFirmware({
  firmware,
  revisionId,
}: {
  firmware: FirmwareSummary;
  revisionId: string;
}) {
  const { t } = useTranslation();
  const unlink = useUnlinkRevision();

  return (
    <li className="grid gap-1 rounded-md border border-border px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <Link
          to="/firmware/$firmwareId"
          params={{ firmwareId: firmware.id }}
          className="min-w-0 font-semibold break-words text-primary hover:underline"
        >
          {firmware.name}
        </Link>
        {firmware.latest_release ? (
          <span className="text-sm">
            {t("firmware.revision.latest")}{" "}
            <span className="font-mono">{firmware.latest_release.version}</span>
          </span>
        ) : (
          <span className="text-sm text-muted">{t("firmware.revision.noRelease")}</span>
        )}
        <button
          type="button"
          aria-label={t("firmware.revision.unlinkFirmware", { name: firmware.name })}
          disabled={unlink.isPending}
          onClick={() => unlink.mutate({ firmwareId: firmware.id, revisionId })}
          className={`${action} ml-auto disabled:opacity-60`}
        >
          {t("firmware.revision.unlink")}
        </button>
      </div>
      {unlink.isError && (
        <p role="alert" className="text-sm text-crit">
          {t("firmware.revision.unlinkError", { name: firmware.name })}
        </p>
      )}
    </li>
  );
}
