import type { FirmwareDetails, FirmwareVersion } from "@wiredex/api-client";
import { type ChangeEvent, useId, useRef } from "react";
import { useTranslation } from "react-i18next";
import { AttachmentRemoveButton } from "../files/attachmentControls";
import { refusalKey, UploadRefusal, useAttachments, useUpload } from "../files/attachments";
import { formatSize } from "../files/sizes";
import { buildsSubject } from "./flashing/useStoredBuild";

type Props = { firmware: FirmwareDetails; version: FirmwareVersion };

/**
 * A released version's builds (spec 20, requirement 4.1): each stored zip of binaries with its
 * size and date, downloadable and removable, newest first, the newest marked as the one *Flash
 * from the browser* writes. With none, the command that makes one is shown to copy; a zip
 * built another way is added here. A draft has no builds: its source can still change, so the
 * panel doesn't render this for one (requirement 4.2).
 */
export function BuildsSection({ firmware, version }: Props) {
  const { t, i18n } = useTranslation();
  const subject = buildsSubject(version.id);
  const builds = useAttachments(subject);
  const upload = useUpload();
  const headingId = useId();
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });

  function add(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    upload.mutate(
      { subject, kind: "firmware_build", file },
      {
        // Emptied, so the same zip, once fixed, is a change again.
        onSettled: () => {
          if (inputRef.current) inputRef.current.value = "";
        },
      },
    );
  }

  const refusal = upload.error instanceof UploadRefusal ? upload.error : null;

  return (
    <section aria-labelledby={headingId} className="grid min-w-0 gap-2">
      <h3 id={headingId} className="text-sm font-semibold">
        {t("firmware.builds.title")}
      </h3>
      <p className="text-sm text-muted">{t("firmware.builds.about")}</p>

      {builds.isPending && <p className="text-sm text-muted">{t("firmware.builds.loading")}</p>}
      {builds.isError && (
        <p role="alert" className="text-sm text-crit">
          {t("firmware.builds.error")}
        </p>
      )}
      {builds.data?.length === 0 && (
        <div className="grid gap-1 text-sm">
          <p className="text-muted">{t("firmware.builds.none")}</p>
          <code className="overflow-x-auto rounded-md bg-surface-2 px-2 py-1 font-mono whitespace-pre">
            {`wiredex firmware build ${quoted(firmware.name)} ${version.version}`}
          </code>
        </div>
      )}
      {builds.data && builds.data.length > 0 && (
        <ul className="grid gap-2">
          {builds.data.map((build, index) => (
            <li
              key={build.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-border bg-surface p-2"
            >
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium break-words">
                  {build.title}
                  {index === 0 && (
                    <span className="ms-2 rounded-full border border-border px-2 py-0.5 text-xs font-semibold">
                      {t("firmware.builds.newest")}
                    </span>
                  )}
                </p>
                <p className="text-sm text-muted">
                  {t("firmware.builds.meta", {
                    size: formatSize(build.size, i18n.language),
                    date: date.format(new Date(build.created_at)),
                  })}
                </p>
              </div>
              <a
                href={build.content_url}
                download
                aria-label={t("files.download", { title: build.title })}
                className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
              >
                {t("firmware.builds.download")}
              </a>
              <AttachmentRemoveButton attachment={build} subject={subject} />
            </li>
          ))}
        </ul>
      )}

      <div className="grid min-w-0 gap-1">
        <label htmlFor={inputId} className="text-sm font-medium">
          {t("firmware.builds.add")}
        </label>
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          accept=".zip,application/zip"
          disabled={upload.isPending}
          onChange={add}
          aria-describedby={`${inputId}-hint`}
          className="min-w-0 text-sm file:mr-3 file:rounded-md file:border file:border-border-strong file:bg-surface file:px-3 file:py-1.5 file:text-text"
        />
        <p id={`${inputId}-hint`} className="text-sm text-muted">
          {t("firmware.builds.addHint")}
        </p>
        {upload.isError && (
          <p role="alert" className="text-sm text-crit">
            {refusal?.status === 415
              ? t("firmware.builds.notABuild")
              : t(refusal ? refusalKey(refusal) : "files.upload.refused.other")}
          </p>
        )}
        <p role="status" className="text-sm text-muted">
          {upload.isSuccess && t("firmware.builds.added")}
        </p>
      </div>
    </section>
  );
}

/** A name as a shell takes it in one piece: quoted when it holds anything but word characters. */
function quoted(name: string): string {
  return /^[\w.-]+$/.test(name) ? name : `"${name.replace(/(["\\$`])/g, "\\$1")}"`;
}
