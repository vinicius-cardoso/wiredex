import { Link } from "@tanstack/react-router";
import type { FirmwareDetails, FirmwareVersion, VersionSummary } from "@wiredex/api-client";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { FirmwareRefusal, useDeleteVersion, useVersion } from "./firmware";
import { refusalKey, statusKey, statusTone } from "./labels";
import { SourceFiles } from "./SourceFiles";

type Props = {
  firmware: FirmwareDetails;
  /** The version as the firmware's page lists it, so the heading shows while it loads. */
  summary: VersionSummary;
  onNewFrom: (version: FirmwareVersion) => void;
  onEdit: (version: FirmwareVersion) => void;
  onRelease: (version: FirmwareVersion) => void;
};

const action = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";

/**
 * One version of a firmware (requirement 11.6): a region named by its heading, `Version 1.2.0`,
 * with its status in words, the version it was started from, linking to it, when it was
 * released and its changelog as written; *Edit* and *Release* for a draft, *New version from
 * this* and *Delete* for any; then its source files. The dialogs live with the page, which
 * stays mounted when a write moves the open version.
 */
export function VersionPanel({ firmware, summary, onNewFrom, onEdit, onRelease }: Props) {
  const { t } = useTranslation();
  const headingId = useId();
  const version = useVersion(summary.id);
  // The loaded version once there is one: it moves with the page's list on every write.
  const shown = version.data ?? summary;

  return (
    <section
      aria-labelledby={headingId}
      className="grid min-w-0 content-start gap-3 rounded-lg border border-border bg-surface p-4"
    >
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 id={headingId} className="font-display text-xl font-semibold break-all">
          {t("firmware.version.heading", { version: shown.version })}
        </h2>
        <span
          className={`rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold ${statusTone[shown.status]}`}
        >
          {t(statusKey(shown.status))}
        </span>
      </div>

      {/* Data first: a refetch that fails keeps showing what was loaded. */}
      {version.data ? (
        <VersionBody
          firmware={firmware}
          version={version.data}
          onNewFrom={onNewFrom}
          onEdit={onEdit}
          onRelease={onRelease}
        />
      ) : version.isError ? (
        <p role="alert" className="text-sm text-crit">
          {t("firmware.version.error")}
        </p>
      ) : (
        <p className="text-sm text-muted">{t("firmware.version.loading")}</p>
      )}
    </section>
  );
}

type BodyProps = Omit<Props, "summary"> & { version: FirmwareVersion };

function VersionBody({ firmware, version, onNewFrom, onEdit, onRelease }: BodyProps) {
  const { t, i18n } = useTranslation();
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });

  return (
    <>
      {(version.based_on || version.released_at) && (
        <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
          {version.based_on && (
            <>
              <dt className="text-muted">{t("firmware.version.basedOn")}</dt>
              <dd>
                <Link
                  to="/firmware/$firmwareId/versions/$versionId"
                  params={{ firmwareId: firmware.id, versionId: version.based_on.id }}
                  className="font-semibold text-primary hover:underline"
                >
                  {version.based_on.version}
                </Link>
              </dd>
            </>
          )}
          {version.released_at && (
            <>
              <dt className="text-muted">{t("firmware.version.releasedOn")}</dt>
              <dd>
                <time dateTime={version.released_at}>
                  {date.format(new Date(version.released_at))}
                </time>
              </dd>
            </>
          )}
        </dl>
      )}

      <div className="grid gap-1">
        <h3 className="text-sm font-semibold">{t("firmware.version.changelog")}</h3>
        {version.changelog ? (
          <p className="max-w-prose whitespace-pre-line break-words">{version.changelog}</p>
        ) : (
          <p className="text-sm text-muted">{t("firmware.version.noChangelog")}</p>
        )}
      </div>

      <div className="flex flex-wrap items-start gap-2">
        {version.editable && (
          <>
            <button type="button" onClick={() => onEdit(version)} className={action}>
              {t("firmware.version.edit")}
            </button>
            <ReleaseButton version={version} onRelease={onRelease} />
          </>
        )}
        <button type="button" onClick={() => onNewFrom(version)} className={action}>
          {t("firmware.version.newFrom")}
        </button>
        <DeleteVersionButton firmware={firmware} version={version} />
      </div>

      <SourceFiles version={version} framework={firmware.framework} />
    </>
  );
}

/**
 * A draft with no file or no changelog can't be released (requirements 6.2, 6.3), so the
 * button stays reachable but unavailable, the reason as its description, rather than vanishing
 * (requirement 11.7); the dialog it opens otherwise asks first.
 */
function ReleaseButton({
  version,
  onRelease,
}: {
  version: FirmwareVersion;
  onRelease: (version: FirmwareVersion) => void;
}) {
  const { t } = useTranslation();
  const reasonId = useId();
  const noFiles = version.files.length === 0;
  const noChangelog = !version.changelog;

  if (noFiles || noChangelog) {
    const reason =
      noFiles && noChangelog
        ? "firmware.version.releaseNeedsBoth"
        : noFiles
          ? "firmware.version.releaseNeedsFiles"
          : "firmware.version.releaseNeedsChangelog";
    return (
      <div className="grid gap-1">
        <button
          type="button"
          aria-disabled="true"
          aria-describedby={reasonId}
          className="cursor-not-allowed rounded-md border border-border px-3 py-1.5 text-sm text-muted"
        >
          {t("firmware.version.release")}
        </button>
        <p id={reasonId} className="max-w-xs text-sm text-muted">
          {t(reason)}
        </p>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onRelease(version)}
      className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90"
    >
      {t("firmware.version.release")}
    </button>
  );
}

/**
 * Deleting asks first, draft or released (requirement 8.1); the versions started from it keep
 * going without a base (8.2). The hook opens the firmware's highest version once it is gone.
 */
function DeleteVersionButton({
  firmware,
  version,
}: {
  firmware: FirmwareDetails;
  version: FirmwareVersion;
}) {
  const { t } = useTranslation();
  const remove = useDeleteVersion();
  const [asking, setAsking] = useState(false);

  if (!asking) {
    return (
      <button
        type="button"
        onClick={() => setAsking(true)}
        className="rounded-md border border-crit px-3 py-1.5 text-sm text-crit hover:bg-surface-2"
      >
        {t("firmware.version.delete")}
      </button>
    );
  }

  const refusal = remove.error instanceof FirmwareRefusal ? remove.error : null;
  const key = refusalKey(refusal?.code ?? null);

  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm">
        {t("firmware.version.deleteQuestion", { version: version.version })}
      </legend>
      {remove.isError && (
        <p role="alert" className="text-sm text-crit">
          {key ? t(key, { item: refusal?.item ?? "" }) : t("firmware.version.deleteError")}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={remove.isPending}
          onClick={() => remove.mutate({ firmwareId: firmware.id, versionId: version.id })}
          className="rounded-md bg-crit px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {t("firmware.version.deleteConfirm")}
        </button>
        <button type="button" onClick={() => setAsking(false)} className={action}>
          {t("firmware.version.deleteCancel")}
        </button>
      </div>
    </fieldset>
  );
}
