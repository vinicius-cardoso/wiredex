import { Link, useNavigate } from "@tanstack/react-router";
import type { FirmwareDetails, FirmwareVersion, VersionSummary } from "@wiredex/api-client";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { revisionName } from "../projects/projects";
import { FirmwareForm } from "./FirmwareForm";
import { openVersion, useDeleteFirmware, useFirmware } from "./firmware";
import { frameworkKey, statusKey } from "./labels";
import { EditVersionDialog, NewVersionDialog, ReleaseDialog } from "./VersionDialogs";
import { VersionPanel } from "./VersionPanel";

type Props = {
  firmwareId: string;
  /** The version the address names; absent means the highest (requirement 11.5). */
  versionId?: string;
};

/**
 * A firmware's page, at `/firmware/$firmwareId` and `/firmware/$firmwareId/versions/$versionId`,
 * opened the way a project's page is: the header (name, board target, framework, the
 * description as written), the revisions it runs on, each a link to its revision, then its
 * versions with the open one marked, beside the open version's panel. *Edit* puts the firmware
 * form in place of the header, leaving the rest in view as a project's revisions stay, and
 * *Delete* asks first.
 */
export function FirmwarePage({ firmwareId, versionId }: Props) {
  const { t } = useTranslation();
  const firmware = useFirmware(firmwareId);

  return (
    <section className="grid gap-6">
      <Link to="/firmware" className="text-sm text-muted hover:text-primary">
        {t("firmware.page.back")}
      </Link>
      {firmware.isPending && <p className="text-muted">{t("firmware.page.loading")}</p>}
      {firmware.isError && (
        <p role="alert" className="text-crit">
          {t("firmware.page.error")}
        </p>
      )}
      {firmware.data && <FirmwareDetail firmware={firmware.data} versionId={versionId} />}
    </section>
  );
}

/**
 * The version dialog open on the page. They live here rather than in the panel: a write can
 * move which version the page opens, which replaces the panel, and a dialog inside it would
 * go before its write's callback ran.
 */
type VersionDialog =
  | { kind: "new"; from: string | null }
  | { kind: "edit"; version: FirmwareVersion }
  | { kind: "release"; version: FirmwareVersion };

function FirmwareDetail({
  firmware,
  versionId,
}: {
  firmware: FirmwareDetails;
  versionId: string | undefined;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [dialog, setDialog] = useState<VersionDialog | null>(null);
  const open = openVersion(firmware, versionId);
  const close = () => setDialog(null);
  const openVersionPage = (version: FirmwareVersion) => {
    setDialog(null);
    void navigate({
      to: "/firmware/$firmwareId/versions/$versionId",
      params: { firmwareId: firmware.id, versionId: version.id },
    });
  };

  return (
    <>
      {editing ? (
        <section className="grid gap-4">
          <h1 className="font-display text-3xl font-semibold tracking-tight">
            {t("firmware.page.editTitle", { name: firmware.name })}
          </h1>
          <FirmwareForm
            firmware={firmware}
            onSaved={() => setEditing(false)}
            onCancel={() => setEditing(false)}
          />
        </section>
      ) : (
        <header className="grid gap-4">
          <h1 className="font-display text-3xl font-semibold tracking-tight break-words">
            {firmware.name}
          </h1>
          <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-[auto_1fr]">
            <dt className="text-sm text-muted">{t("firmware.page.target")}</dt>
            {/* A long FQBN wraps rather than widening the page (requirement 11.16). */}
            <dd className="font-mono text-sm break-all">{firmware.target}</dd>
            <dt className="text-sm text-muted">{t("firmware.page.framework")}</dt>
            <dd className="text-sm">{t(frameworkKey(firmware.framework))}</dd>
          </dl>
          {firmware.description && (
            <p className="max-w-prose whitespace-pre-line break-words">{firmware.description}</p>
          )}
          <div className="flex flex-wrap items-start gap-3">
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
            >
              {t("firmware.page.edit")}
            </button>
            <DeleteFirmwareButton firmware={firmware} />
          </div>
        </header>
      )}
      <RunsOn firmware={firmware} />

      {/* minmax(0, …): a long line of source scrolls in its box, never the page (11.16). */}
      <div className="grid min-w-0 gap-4 md:grid-cols-[14rem_minmax(0,1fr)]">
        <VersionsNav
          firmware={firmware}
          open={open}
          onNew={() => setDialog({ kind: "new", from: null })}
        />
        {open ? (
          // Keyed, so a question asked on one version doesn't follow to the next.
          <VersionPanel
            key={open.id}
            firmware={firmware}
            summary={open}
            onNewFrom={(version) => setDialog({ kind: "new", from: version.id })}
            onEdit={(version) => setDialog({ kind: "edit", version })}
            onRelease={(version) => setDialog({ kind: "release", version })}
          />
        ) : (
          <NoVersion firmware={firmware} named={versionId !== undefined} />
        )}
      </div>

      {dialog?.kind === "new" && (
        <NewVersionDialog
          firmware={firmware}
          from={dialog.from}
          onClose={close}
          onStarted={openVersionPage}
        />
      )}
      {dialog?.kind === "edit" && (
        // Opened by its own address after a save, so a new number that moves it in the
        // order keeps it open.
        <EditVersionDialog version={dialog.version} onClose={close} onSaved={openVersionPage} />
      )}
      {dialog?.kind === "release" && (
        <ReleaseDialog version={dialog.version} onClose={close} onReleased={close} />
      )}
    </>
  );
}

/** The firmware's versions, highest first, each a link with its status in words (11.5). */
function VersionsNav({
  firmware,
  open,
  onNew,
}: {
  firmware: FirmwareDetails;
  open: VersionSummary | undefined;
  onNew: () => void;
}) {
  const { t } = useTranslation();
  const headingId = useId();

  return (
    <nav aria-labelledby={headingId} className="grid min-w-0 content-start gap-2">
      <h2 id={headingId} className="text-sm font-semibold text-muted">
        {t("firmware.page.versions")}
      </h2>
      {firmware.versions.length > 0 && (
        <ul className="grid gap-1">
          {firmware.versions.map((version) => {
            const current = version.id === open?.id;
            return (
              <li key={version.id}>
                <Link
                  to="/firmware/$firmwareId/versions/$versionId"
                  params={{ firmwareId: firmware.id, versionId: version.id }}
                  // Set here rather than left to the router: the firmware's own address opens
                  // the highest version, whose link the router doesn't see as active.
                  aria-current={current ? "page" : undefined}
                  activeProps={{}}
                  className={`block rounded-md px-3 py-1.5 text-sm break-all hover:bg-surface-2 ${
                    current ? "bg-surface-2 font-semibold text-primary" : ""
                  }`}
                >
                  {t("firmware.page.versionEntry", {
                    version: version.version,
                    status: t(statusKey(version.status)),
                  })}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      <button
        type="button"
        onClick={onNew}
        className="justify-self-start rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
      >
        {t("firmware.page.newVersion")}
      </button>
    </nav>
  );
}

/** No version open: the firmware has none yet, or the address names one it doesn't hold. */
function NoVersion({ firmware, named }: { firmware: FirmwareDetails; named: boolean }) {
  const { t } = useTranslation();
  const highest = firmware.versions[0];

  if (!named || !highest) {
    return (
      <div className="grid content-start rounded-lg border border-dashed border-border-strong bg-surface p-6">
        <p className="text-muted">
          {t(named ? "firmware.page.noSuchVersion" : "firmware.page.noVersions")}
        </p>
      </div>
    );
  }

  return (
    <div
      role="alert"
      className="grid content-start justify-items-start gap-2 rounded-lg border border-dashed border-border-strong bg-surface p-6"
    >
      <p>{t("firmware.page.noSuchVersion")}</p>
      <Link
        to="/firmware/$firmwareId/versions/$versionId"
        params={{ firmwareId: firmware.id, versionId: highest.id }}
        className="font-semibold text-primary hover:underline"
      >
        {t("firmware.page.openHighest", { version: highest.version })}
      </Link>
    </div>
  );
}

/**
 * The revisions the firmware runs on, in the order they were linked (requirement 3.5), each a
 * link to its revision on its project's page. One the workspace lost is already left out.
 */
function RunsOn({ firmware }: { firmware: FirmwareDetails }) {
  const { t } = useTranslation();
  const headingId = useId();

  return (
    <section aria-labelledby={headingId} className="grid gap-1">
      <h2 id={headingId} className="text-sm font-semibold text-muted">
        {t("firmware.page.runsOn")}
      </h2>
      {firmware.runs_on.length === 0 ? (
        <p className="text-sm text-muted">{t("firmware.page.runsOnNothing")}</p>
      ) : (
        <ul className="grid gap-1 break-words">
          {firmware.runs_on.map((revision) => (
            <li key={revision.revision_id}>
              <Link
                to="/projects/$projectId/revisions/$revisionId"
                params={{ projectId: revision.project_id, revisionId: revision.revision_id }}
                className="text-primary hover:underline"
              >
                {t("firmware.page.runsOnEntry", {
                  project: revision.project_name,
                  revision: revisionName(t, revision),
                })}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Deleting asks first: the firmware goes with its versions, files and links (requirement 1.9). */
function DeleteFirmwareButton({ firmware }: { firmware: FirmwareDetails }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const remove = useDeleteFirmware();
  const [asking, setAsking] = useState(false);

  if (!asking) {
    return (
      <button
        type="button"
        onClick={() => setAsking(true)}
        className="rounded-md border border-crit px-4 py-2 text-crit hover:bg-surface-2"
      >
        {t("firmware.page.delete")}
      </button>
    );
  }

  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm">
        {t("firmware.page.deleteQuestion", { name: firmware.name })}
      </legend>
      {remove.isError && (
        <p role="alert" className="text-sm text-crit">
          {t("firmware.page.deleteError")}
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={remove.isPending}
          onClick={() =>
            remove.mutate(firmware.id, { onSuccess: () => void navigate({ to: "/firmware" }) })
          }
          className="rounded-md bg-crit px-4 py-2 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {t("firmware.page.deleteConfirm")}
        </button>
        <button
          type="button"
          onClick={() => setAsking(false)}
          className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
        >
          {t("firmware.page.deleteCancel")}
        </button>
      </div>
    </fieldset>
  );
}
