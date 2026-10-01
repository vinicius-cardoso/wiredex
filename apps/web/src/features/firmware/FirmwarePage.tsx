import { Link, useNavigate } from "@tanstack/react-router";
import type { FirmwareDetails } from "@wiredex/api-client";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { revisionName } from "../projects/projects";
import { FirmwareForm } from "./FirmwareForm";
import { useDeleteFirmware, useFirmware } from "./firmware";
import { frameworkKey } from "./labels";

type Props = { firmwareId: string };

/**
 * A firmware's page, at `/firmware/$firmwareId`, opened the way a project's page is: the
 * header (name, board target, framework, the description as written) and the revisions it
 * runs on, each a link to its revision. *Edit* puts the firmware form in place of the header,
 * leaving *Runs on* in view as a project's revisions stay, and *Delete* asks first.
 */
export function FirmwarePage({ firmwareId }: Props) {
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
      {firmware.data && <FirmwareDetail firmware={firmware.data} />}
    </section>
  );
}

function FirmwareDetail({ firmware }: { firmware: FirmwareDetails }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);

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
    </>
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
