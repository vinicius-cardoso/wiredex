import { Link } from "@tanstack/react-router";
import type { FirmwareDetails, FirmwareVersion, VersionSummary } from "@wiredex/api-client";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Block, type BlockSpan } from "../../shared/ui/block";
import { BlockingFlashes } from "./BlockingFlashes";
import { BuildsSection } from "./BuildsSection";
import { FirmwareRefusal, useDeleteVersion, useVersion } from "./firmware";
import { refusalKey, statusKey, statusTone } from "./labels";
import { SourceFiles } from "./SourceFiles";
import { comparisonBase } from "./source/comparable";

type Props = {
  firmware: FirmwareDetails;
  /** The version as the firmware's page lists it, so the heading shows while it loads. */
  summary: VersionSummary;
  onNewFrom: (version: FirmwareVersion) => void;
  onEdit: (version: FirmwareVersion) => void;
  onRelease: (version: FirmwareVersion) => void;
  onLogFlash: (version: FirmwareVersion) => void;
  onWriteFlash: (version: FirmwareVersion) => void;
  span?: BlockSpan | undefined;
};

const action = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";
const primary =
  "rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90";

/**
 * One version of a firmware (requirement 11.6): a region named by its heading, `Version 1.2.0`,
 * with its status in words, the version it was started from, linking to it, when it was
 * released and its changelog as written; *Edit* and *Release* for a draft, *Log a flash* and
 * *Flash from the browser* for a release (spec 15, 8.3), right above the files it copies, then *New version from this*,
 * *Compare with* its base or the version below it, and *Delete* for any; then its source
 * files. Its status is the block's badge, beside the heading but not in the region's name.
 * The dialogs live with the page, which stays mounted when a write moves the open
 * version.
 */
export function VersionPanel({
  firmware,
  summary,
  onNewFrom,
  onEdit,
  onRelease,
  onLogFlash,
  onWriteFlash,
  span,
}: Props) {
  const { t } = useTranslation();
  const version = useVersion(summary.id);
  // The loaded version once there is one: it moves with the page's list on every write.
  const shown = version.data ?? summary;

  return (
    <Block
      title={t("firmware.version.heading", { version: shown.version })}
      badge={
        <span
          className={`rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold ${statusTone[shown.status]}`}
        >
          {t(statusKey(shown.status))}
        </span>
      }
      span={span}
    >
      {/* Data first: a refetch that fails keeps showing what was loaded. */}
      {version.data ? (
        <VersionBody
          firmware={firmware}
          version={version.data}
          onNewFrom={onNewFrom}
          onEdit={onEdit}
          onRelease={onRelease}
          onLogFlash={onLogFlash}
          onWriteFlash={onWriteFlash}
        />
      ) : version.isError ? (
        <p role="alert" className="text-sm text-crit">
          {t("firmware.version.error")}
        </p>
      ) : (
        <p className="text-sm text-muted">{t("firmware.version.loading")}</p>
      )}
    </Block>
  );
}

type BodyProps = Omit<Props, "summary" | "span"> & { version: FirmwareVersion };

function VersionBody({
  firmware,
  version,
  onNewFrom,
  onEdit,
  onRelease,
  onLogFlash,
  onWriteFlash,
}: BodyProps) {
  const { t, i18n } = useTranslation();
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });
  // What *Compare with* opens against (decision 9): none for a first version.
  const baseId = comparisonBase(firmware.versions, version.id);
  const base = firmware.versions.find((listed) => listed.id === baseId);

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
        {/* Only a release is flashed: a draft can still change (spec 15, decision 2). */}
        {version.status === "released" && (
          <>
            <button type="button" onClick={() => onLogFlash(version)} className={primary}>
              {t("firmware.flash.log")}
            </button>
            <button type="button" onClick={() => onWriteFlash(version)} className={action}>
              {t("firmware.flash.write.open")}
            </button>
          </>
        )}
        <button type="button" onClick={() => onNewFrom(version)} className={action}>
          {t("firmware.version.newFrom")}
        </button>
        {base && (
          <Link
            to="/firmware/$firmwareId/compare"
            params={{ firmwareId: firmware.id }}
            search={{ from: base.id, to: version.id }}
            className={action}
          >
            {t("firmware.compare.with", { version: base.version })}
          </Link>
        )}
        <DeleteVersionButton firmware={firmware} version={version} />
      </div>

      {/* Only a release holds builds: a draft's source can still change (spec 20, decision 3). */}
      {version.status === "released" && <BuildsSection firmware={firmware} version={version} />}

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
    <button type="button" onClick={() => onRelease(version)} className={primary}>
      {t("firmware.version.release")}
    </button>
  );
}

/**
 * Deleting asks first, draft or released (requirement 8.1); the versions started from it keep
 * going without a base (8.2). The hook opens the firmware's highest version once it is gone.
 * A version a board's log names stays, and the refusal lists those flashes to remove
 * (spec 15, 8.7).
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
      {refusal && refusal.flashes.length > 0 && <BlockingFlashes flashes={refusal.flashes} />}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={remove.isPending}
          onClick={() => remove.mutate({ firmwareId: firmware.id, versionId: version.id })}
          className="rounded-md bg-crit px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {t("firmware.version.deleteConfirm")}
        </button>
        <button
          type="button"
          onClick={() => {
            // A refusal belongs to the question it answered, not to the next one asked.
            remove.reset();
            setAsking(false);
          }}
          className={action}
        >
          {t("firmware.version.deleteCancel")}
        </button>
      </div>
    </fieldset>
  );
}
