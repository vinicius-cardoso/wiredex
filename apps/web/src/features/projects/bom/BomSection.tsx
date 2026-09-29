import type { BomLine, BomPart, RevisionDetails } from "@wiredex/api-client";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { statusKey } from "../status";
import { useBom } from "./bom";
import { blank, PartLink, ShortageReport } from "./ShortageReport";
import { stockStatusKey, stockStatusTone } from "./stockStatus";

export const bomCell = "py-2 pr-4 align-top";

/**
 * A revision's bill of materials (requirement 11.1): a region named by its heading, with the
 * shortage report and a table of the lines, each with its designators, part, quantity, notes
 * and its part's stock status. A revision that isn't a draft shows its lines with a note
 * saying why they can't change (requirement 11.9). The table scrolls inside its own box.
 */
export function BomSection({ revision }: { revision: RevisionDetails }) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const bom = useBom(revision.id);
  const parts = new Map((bom.data?.report.parts ?? []).map((part) => [part.part_id, part]));

  return (
    <section aria-labelledby={headingId} className="grid gap-3">
      <h3 id={headingId} className="font-display text-xl font-semibold">
        {t("projects.bom.title")}
      </h3>

      {bom.isPending && <p className="text-muted">{t("projects.bom.loading")}</p>}
      {bom.isError && (
        <p role="alert" className="text-crit">
          {t("projects.bom.error")}
        </p>
      )}

      {bom.data && !bom.data.editable && (
        <p className="text-sm text-muted">
          {t("projects.bom.locked", {
            status: t(statusKey(bom.data.status)).toLocaleLowerCase(i18n.language),
          })}
        </p>
      )}

      {bom.data && bom.data.lines.length === 0 && (
        <p className="text-muted">{t("projects.bom.empty")}</p>
      )}

      {bom.data && bom.data.lines.length > 0 && (
        <>
          <ShortageReport report={bom.data.report} />
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <caption className="sr-only">{t("projects.bom.caption")}</caption>
              <thead>
                <tr className="border-b border-border text-muted">
                  <th scope="col" className={`${bomCell} font-medium`}>
                    {t("projects.bom.columns.designators")}
                  </th>
                  <th scope="col" className={`${bomCell} font-medium`}>
                    {t("projects.bom.columns.part")}
                  </th>
                  <th scope="col" className={`${bomCell} font-medium`}>
                    {t("projects.bom.columns.quantity")}
                  </th>
                  <th scope="col" className={`${bomCell} font-medium`}>
                    {t("projects.bom.columns.notes")}
                  </th>
                  <th scope="col" className={`${bomCell} font-medium`}>
                    {t("projects.bom.columns.stock")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {bom.data.lines.map((line) => (
                  <tr key={line.id} className="border-b border-border">
                    <LineCells line={line} part={parts.get(line.part_id)} />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

/** A line's five cells as they read when it isn't being edited. */
export function LineCells({ line, part }: { line: BomLine; part: BomPart | undefined }) {
  const { t } = useTranslation();
  return (
    <>
      <td className={`${bomCell} font-mono`}>{line.designator_text || blank}</td>
      <td className={bomCell}>
        {part ? <PartLink part={part} /> : blank}
        {part?.part?.mpn && <span className="block font-mono text-muted">{part.part.mpn}</span>}
      </td>
      <td className={bomCell}>{line.quantity}</td>
      <td className={bomCell}>{line.notes ?? blank}</td>
      <td className={`${bomCell} ${part ? stockStatusTone[part.status] : ""}`}>
        {part ? t(stockStatusKey(part.status)) : blank}
      </td>
    </>
  );
}
