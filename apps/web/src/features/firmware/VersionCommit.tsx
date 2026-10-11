import type { FirmwareDetails, FirmwareVersion } from "@wiredex/api-client";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { FirmwareRefusal, useLinkCommit } from "./firmware";
import { commitUrl, shortCommit } from "./git";

const action = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";

/**
 * The commit a version was cut from (spec 22, requirement 3): its first seven digits, a link
 * to the commit's page when the firmware has a repository, and a button that opens one field
 * to set, change or clear it. A released version changes it too: the commit points at the
 * code, it isn't part of it.
 */
export function VersionCommit({
  firmware,
  version,
}: {
  firmware: FirmwareDetails;
  version: FirmwareVersion;
}) {
  const { t } = useTranslation();
  const link = useLinkCommit();
  const inputId = useId();
  const [typed, setTyped] = useState<string | null>(null);

  if (typed === null) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        {version.commit ? (
          firmware.repository ? (
            <a
              href={commitUrl(firmware.repository, version.commit)}
              target="_blank"
              rel="noreferrer"
              title={version.commit}
              className="font-mono font-semibold text-primary hover:underline"
            >
              {shortCommit(version.commit)}
            </a>
          ) : (
            <span title={version.commit} className="font-mono">
              {shortCommit(version.commit)}
            </span>
          )
        ) : (
          <span className="text-muted">{t("firmware.version.noCommit")}</span>
        )}
        <button
          type="button"
          onClick={() => {
            link.reset();
            setTyped(version.commit ?? "");
          }}
          className="text-sm text-primary hover:underline"
        >
          {t(version.commit ? "firmware.version.changeCommit" : "firmware.version.linkCommit")}
        </button>
      </div>
    );
  }

  function save(event: FormEvent) {
    event.preventDefault();
    const commit = (typed ?? "").trim();
    link.mutate(
      { versionId: version.id, commit: commit === "" ? null : commit },
      { onSuccess: () => setTyped(null) },
    );
  }

  const refusal = link.error instanceof FirmwareRefusal ? link.error : null;
  const problem = link.isError
    ? t(
        refusal?.code === "invalid_commit"
          ? "firmware.refusal.invalid_commit"
          : "firmware.version.commitError",
      )
    : null;

  return (
    <form onSubmit={save} className="grid max-w-md gap-1">
      <label htmlFor={inputId} className="sr-only">
        {t("firmware.version.commitLabel", { version: version.version })}
      </label>
      <div className="flex flex-wrap gap-2">
        <input
          id={inputId}
          type="text"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          // biome-ignore lint/a11y/noAutofocus: the field opens because its button was pressed
          autoFocus
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          placeholder="a1b2c3d"
          aria-invalid={problem ? true : undefined}
          aria-describedby={`${inputId}-help`}
          className="min-w-0 flex-1 rounded-md border border-border-strong bg-surface px-2 py-1.5 font-mono text-sm text-text"
        />
        <button type="submit" disabled={link.isPending} className={action}>
          {t(link.isPending ? "firmware.version.commitSaving" : "firmware.version.commitSave")}
        </button>
        <button type="button" onClick={() => setTyped(null)} className={action}>
          {t("firmware.version.commitCancel")}
        </button>
      </div>
      <p
        id={`${inputId}-help`}
        role={problem ? "alert" : undefined}
        className={`text-sm ${problem ? "text-crit" : "text-muted"}`}
      >
        {problem ?? t("firmware.version.commitHint")}
      </p>
    </form>
  );
}
