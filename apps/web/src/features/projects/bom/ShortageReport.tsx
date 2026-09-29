import { Link } from "@tanstack/react-router";
import type { BomPart, ShortageReport as Report } from "@wiredex/api-client";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { stockStatusTone } from "./stockStatus";

const cell = "py-2 pr-4 align-top";

/**
 * What the BOM is missing (requirement 11.8): the summary's counts, then each part short with
 * its need, available stock and shortage, and each part the catalog no longer holds, every one
 * linking to its part page; or *Nothing is short* once the BOM is complete. The table scrolls
 * inside its own box, so a phone never scrolls the page sideways (requirement 11.17).
 *
 * For a revision that isn't a draft, the report reads against free stock as for a draft, so its
 * heading says what building it again would be missing rather than plain shortages (requirement
 * 13.11).
 */
export function ShortageReport({ report, rebuild = false }: { report: Report; rebuild?: boolean }) {
  const { t } = useTranslation();
  const headingId = useId();
  const { summary } = report;
  const missing = report.parts.filter(
    (part) => part.status === "short" || part.status === "unknown_part",
  );
  const counts = [
    [t("projects.bom.report.lines"), summary.lines],
    [t("projects.bom.report.parts"), summary.parts],
    [t("projects.bom.report.shortParts"), summary.short_parts],
    [t("projects.bom.report.shortPieces"), summary.short_pieces],
    [t("projects.bom.report.notStocked"), summary.not_stocked_parts],
    [t("projects.bom.report.unknown"), summary.unknown_parts],
  ] as const;

  return (
    <section aria-labelledby={headingId} className="grid gap-2">
      <h4 id={headingId} className="font-semibold">
        {t(rebuild ? "projects.bom.report.rebuildTitle" : "projects.bom.report.title")}
      </h4>
      <dl className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {counts.map(([label, value]) => (
          <div key={label} className="flex gap-1">
            <dt className="text-muted">{label}</dt>
            <dd className="font-semibold">{value}</dd>
          </div>
        ))}
      </dl>

      {summary.complete ? (
        <p className="text-ok">{t("projects.bom.report.complete")}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">{t("projects.bom.report.missing")}</caption>
            <thead>
              <tr className="border-b border-border text-muted">
                <th scope="col" className={`${cell} font-medium`}>
                  {t("projects.bom.columns.part")}
                </th>
                <th scope="col" className={`${cell} font-medium`}>
                  {t("projects.bom.report.need")}
                </th>
                <th scope="col" className={`${cell} font-medium`}>
                  {t("projects.bom.report.available")}
                </th>
                <th scope="col" className={`${cell} font-medium`}>
                  {t("projects.bom.report.short")}
                </th>
              </tr>
            </thead>
            <tbody>
              {missing.map((part) => (
                <tr key={part.part_id} className="border-b border-border">
                  <th scope="row" className={`${cell} font-medium`}>
                    <PartLink part={part} />
                  </th>
                  <td className={cell}>{part.need}</td>
                  <td className={cell}>{part.available ?? blank}</td>
                  <td className={`${cell} font-semibold ${stockStatusTone[part.status]}`}>
                    {part.status === "short" ? part.short : blank}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/**
 * A part on the BOM as a link to its page. An unknown part has no name left to show, so it
 * reads as unknown; its link still leads to the page that says it is gone.
 */
export function PartLink({ part }: { part: BomPart }) {
  const { t } = useTranslation();
  return (
    <Link
      to="/parts/$partId"
      params={{ partId: part.part_id }}
      className={part.part ? "text-primary hover:underline" : "text-warn hover:underline"}
    >
      {part.part?.name ?? t("projects.bom.unknownPart")}
    </Link>
  );
}

/** An em dash for a number a part doesn't have: the same in both languages, so not a key. */
export const blank = "—";
