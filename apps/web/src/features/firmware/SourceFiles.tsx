import type { FirmwareVersion, SourceFile } from "@wiredex/api-client";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { formatSize } from "../files/sizes";

type Props = { version: FirmwareVersion };

/**
 * A version's source files in the API's order, `.ino` first (requirement 7.10): an index of
 * links when there are several, then each file as a region named by its path, with its size,
 * its line count and its text exactly as stored. 14-firmware-viewer puts its viewer where the
 * `<pre>` is.
 */
export function SourceFiles({ version }: Props) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const files = version.files;

  return (
    <section aria-labelledby={headingId} className="grid min-w-0 gap-3">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h3 id={headingId} className="text-sm font-semibold">
          {t("firmware.files.title")}
        </h3>
        {files.length > 0 && (
          <p className="text-sm text-muted">
            {t("firmware.files.summary", {
              count: files.length,
              size: formatSize(version.size, i18n.language),
            })}
          </p>
        )}
      </div>

      {files.length === 0 && <p className="text-sm text-muted">{t("firmware.files.empty")}</p>}

      {files.length > 1 && (
        <nav aria-label={t("firmware.files.index")}>
          <ul className="flex flex-wrap gap-x-4 gap-y-1">
            {files.map((file) => (
              <li key={file.id} className="min-w-0">
                <a
                  href={`#${anchorOf(file)}`}
                  className="font-mono text-sm break-all text-primary hover:underline"
                >
                  {file.path}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      )}

      {files.map((file) => (
        <SourceFileView key={file.id} file={file} />
      ))}
    </section>
  );
}

function SourceFileView({ file }: { file: SourceFile }) {
  const { t, i18n } = useTranslation();
  const pathId = useId();

  return (
    <section id={anchorOf(file)} aria-labelledby={pathId} className="grid min-w-0 gap-1">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h4 id={pathId} className="font-mono text-sm font-semibold break-all">
          {file.path}
        </h4>
        <p className="text-xs text-muted">
          {t("firmware.files.meta", {
            count: file.lines,
            size: formatSize(file.size, i18n.language),
          })}
        </p>
      </div>
      {/* A long line scrolls inside the box, never the page (requirement 11.16). */}
      <pre className="max-h-[32rem] overflow-auto rounded-md border border-border bg-surface-2 p-3 font-mono text-sm leading-relaxed">
        <code>{file.content}</code>
      </pre>
    </section>
  );
}

/** The file's id is a UUID, so the anchor is unique on the page and safe in a URL. */
function anchorOf(file: SourceFile): string {
  return `file-${file.id}`;
}
