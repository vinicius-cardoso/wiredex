import { Link, useNavigate } from "@tanstack/react-router";
import type { FirmwareDetails, VersionSummary } from "@wiredex/api-client";
import { lazy, Suspense, useId } from "react";
import { useTranslation } from "react-i18next";
import { control } from "../inventory/StockDialog";
import { FirmwareRefusal, useFirmware, useVersion } from "./firmware";
import { statusKey } from "./labels";
import { type CompareSearch, comparisonBase } from "./source/comparable";
import { SourceErrorBoundary } from "./source/SourceErrorBoundary";

// jsdiff, the comparison and the highlighter load with the first comparison shown, not with
// the app (decision 5, requirement 7.4).
const ComparisonView = lazy(() =>
  import("./source/ComparisonView").then((module) => ({ default: module.ComparisonView })),
);

type Props = { firmwareId: string; search: CompareSearch };

/**
 * What changed between two versions of a firmware, at `/firmware/$firmwareId/compare` with
 * both versions in the address (decision 9): the firmware's name linking back, the *From* and
 * *To* selects over all of its versions, drafts included, then the comparison itself. Without
 * a pair in the address it opens the highest version against its base.
 */
export function ComparePage({ firmwareId, search }: Props) {
  const { t } = useTranslation();
  const firmware = useFirmware(firmwareId);

  return (
    <section className="grid min-w-0 gap-6">
      {firmware.data ? (
        <Link
          to="/firmware/$firmwareId"
          params={{ firmwareId }}
          className="text-sm break-words text-muted hover:text-primary"
        >
          {t("firmware.compare.back", { name: firmware.data.name })}
        </Link>
      ) : (
        <Link to="/firmware" className="text-sm text-muted hover:text-primary">
          {t("firmware.page.back")}
        </Link>
      )}
      <h1 className="font-display text-2xl font-semibold tracking-tight">
        {t("firmware.compare.title")}
      </h1>
      {/* Data first: a refetch that fails keeps showing what was loaded. */}
      {firmware.data ? (
        <Comparing firmware={firmware.data} search={search} />
      ) : firmware.isError ? (
        <p role="alert" className="text-crit">
          {t("firmware.page.error")}
        </p>
      ) : (
        <p className="text-muted">{t("firmware.page.loading")}</p>
      )}
    </section>
  );
}

/**
 * The two selects and what they name. Each change is a new entry in the history, so Back walks
 * the comparisons seen (requirement 4.7); a version that isn't the firmware's, or the same one
 * on both sides, is said in place of the comparison, the selects still there (4.8).
 */
function Comparing({ firmware, search }: { firmware: FirmwareDetails; search: CompareSearch }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const versions = firmware.versions;
  const highest = versions[0];
  // None only when the firmware has fewer than two versions: any other has one below.
  const base = highest ? comparisonBase(versions, highest.id) : null;

  if (!highest || !base) return <p className="text-muted">{t("firmware.compare.tooFew")}</p>;
  const { from, to } =
    search.from !== undefined && search.to !== undefined
      ? { from: search.from, to: search.to }
      : { from: base, to: highest.id };
  const listed = (id: string) => versions.some((version) => version.id === id);
  const choose = (next: { from: string; to: string }) =>
    void navigate({
      to: "/firmware/$firmwareId/compare",
      params: { firmwareId: firmware.id },
      search: next,
    });

  return (
    <>
      <div className="flex flex-wrap gap-4">
        <VersionSelect
          label={t("firmware.compare.from")}
          value={from}
          versions={versions}
          onChange={(id) => choose({ from: id, to })}
        />
        <VersionSelect
          label={t("firmware.compare.to")}
          value={to}
          versions={versions}
          onChange={(id) => choose({ from, to: id })}
        />
      </div>
      {!listed(from) || !listed(to) ? (
        <p role="alert">{t("firmware.compare.noSuchVersion")}</p>
      ) : from === to ? (
        <p role="alert">{t("firmware.compare.sameVersion")}</p>
      ) : (
        <Sides fromId={from} toId={to} />
      )}
    </>
  );
}

type SelectProps = {
  label: string;
  value: string;
  versions: VersionSummary[];
  onChange: (versionId: string) => void;
};

/** Every version, highest first, named as the *Versions* nav names it: *1.2.0 · Draft*. */
function VersionSelect({ label, value, versions, onChange }: SelectProps) {
  const { t } = useTranslation();
  const id = useId();
  const listed = versions.some((version) => version.id === value);

  return (
    <div className="grid min-w-0 gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <select
        id={id}
        // An id the firmware doesn't list shows as a choice still to make.
        value={listed ? value : ""}
        onChange={(event) => onChange(event.target.value)}
        // A long pre-release number shortens the select rather than widening a phone's page.
        className={`${control} max-w-full`}
      >
        {!listed && (
          <option value="" disabled>
            {t("firmware.compare.choose")}
          </option>
        )}
        {versions.map((version) => (
          <option key={version.id} value={version.id}>
            {t("firmware.page.versionEntry", {
              version: version.version,
              status: t(statusKey(version.status)),
            })}
          </option>
        ))}
      </select>
    </div>
  );
}

/**
 * Both versions' files, read through 13's cache, then their comparison once its chunk arrives.
 * A version the firmware listed that answers 404 went meanwhile, which reads as one that isn't
 * the firmware's (Error Handling).
 */
function Sides({ fromId, toId }: { fromId: string; toId: string }) {
  const { t } = useTranslation();
  const from = useVersion(fromId);
  const to = useVersion(toId);

  if (from.data && to.data) {
    return (
      // Keyed by the pair, so a comparison that failed doesn't stay failed for the next.
      <SourceErrorBoundary
        key={`${fromId} ${toId}`}
        fallback={
          <p role="alert" className="text-crit">
            {t("firmware.compare.failed")}
          </p>
        }
      >
        <Suspense fallback={<p className="text-muted">{t("firmware.compare.computing")}</p>}>
          <ComparisonView from={from.data} to={to.data} />
        </Suspense>
      </SourceErrorBoundary>
    );
  }
  const gone = [from.error, to.error].some(
    (error) => error instanceof FirmwareRefusal && error.status === 404,
  );
  if (gone) return <p role="alert">{t("firmware.compare.noSuchVersion")}</p>;
  if (from.isError || to.isError) {
    return (
      <p role="alert" className="text-crit">
        {t("firmware.compare.error")}
      </p>
    );
  }
  return <p className="text-muted">{t("firmware.compare.loading")}</p>;
}
