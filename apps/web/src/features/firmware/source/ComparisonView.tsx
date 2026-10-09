import type { FirmwareVersion } from "@wiredex/api-client";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { formatSize } from "../../files/sizes";
import { type Comparison, compareVersions, type FileComparison, type FileStatus } from "./compare";
import { DiffTable } from "./DiffTable";
import { SideBySideDiff } from "./SideBySideDiff";
import { useSideBySide } from "./useSideBySide";

type Props = {
  from: FirmwareVersion;
  to: FirmwareVersion;
  /** Requirement 4.9's second unless a test says otherwise. */
  timeoutMs?: number | undefined;
};

type Shown = Exclude<FileStatus, "unchanged">;

const REGION = {
  added: "firmware.compare.fileAdded",
  removed: "firmware.compare.fileRemoved",
  changed: "firmware.compare.fileChanged",
} as const satisfies Record<Shown, string>;

const BADGE = {
  added: "firmware.compare.status.added",
  removed: "firmware.compare.status.removed",
  changed: "firmware.compare.status.changed",
} as const satisfies Record<Shown, string>;

/**
 * Two versions' comparison, computed here in the browser (decision 7): the summary's counts,
 * or that the two hold the same files (requirements 4.4, 4.5); the unchanged files named
 * without their text; then a region per changed, added or removed file, named by its path and
 * status, holding its table: the two versions side by side where the window has room for both,
 * one column of changes where it doesn't. Loaded lazily with jsdiff and the highlighter (decision 5).
 */
export function ComparisonView({ from, to, timeoutMs }: Props) {
  const { t, i18n } = useTranslation();
  const comparison = useMemo(
    () => compareVersions(from.files, to.files, timeoutMs === undefined ? {} : { timeoutMs }),
    [from.files, to.files, timeoutMs],
  );
  const unchanged = comparison.files.filter((file) => file.status === "unchanged");
  const changes = comparison.files.filter((file) => file.status !== "unchanged");
  const paths = new Intl.ListFormat(i18n.language, { type: "conjunction" });

  return (
    <div className="grid min-w-0 gap-6">
      <div className="grid gap-1">
        {changes.length === 0 ? (
          <p>{t("firmware.compare.same")}</p>
        ) : (
          <Summary comparison={comparison} />
        )}
        {unchanged.length > 0 && (
          <p className="text-sm break-words text-muted">
            {t("firmware.compare.unchanged", {
              paths: paths.format(unchanged.map((file) => file.path)),
            })}
          </p>
        )}
      </div>
      {changes.map((file) => (
        <FileChanges key={file.path} file={file} status={file.status as Shown} />
      ))}
    </div>
  );
}

/** How many files were added, removed and changed, and how many lines (requirement 4.4). */
function Summary({ comparison: { counts, lines } }: { comparison: Comparison }) {
  const { t } = useTranslation();
  const items = {
    filesChanged: t("firmware.compare.filesChanged", { count: counts.changed }),
    filesAdded: t("firmware.compare.filesAdded", { count: counts.added }),
    filesRemoved: t("firmware.compare.filesRemoved", { count: counts.removed }),
    linesAdded: t("firmware.compare.linesAdded", { count: lines.added }),
    linesRemoved: t("firmware.compare.linesRemoved", { count: lines.removed }),
  };

  return (
    <ul aria-label={t("firmware.compare.summary")} className="flex flex-wrap gap-x-4 gap-y-1">
      {Object.entries(items).map(([name, item]) => (
        <li key={name}>{item}</li>
      ))}
    </ul>
  );
}

/**
 * One file's changes under its path and its status in words. A file whose changes took longer
 * than the timeout shows its two sizes instead of its lines (requirement 4.9).
 */
function FileChanges({ file, status }: { file: FileComparison; status: Shown }) {
  const { t, i18n } = useTranslation();
  const Diff = useSideBySide() ? SideBySideDiff : DiffTable;

  return (
    <section aria-label={t(REGION[status], { path: file.path })} className="grid min-w-0 gap-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="font-mono text-sm font-semibold break-all">{file.path}</h2>
        <span className="rounded-full border border-border px-2 py-0.5 text-xs font-semibold">
          {t(BADGE[status])}
        </span>
      </div>
      {file.hunks === null ? (
        <p className="text-sm text-muted">
          {t("firmware.compare.tooSlow", {
            from: formatSize(file.from?.size ?? 0, i18n.language),
            to: formatSize(file.to?.size ?? 0, i18n.language),
          })}
        </p>
      ) : (
        <Diff file={file} hunks={file.hunks} />
      )}
    </section>
  );
}
