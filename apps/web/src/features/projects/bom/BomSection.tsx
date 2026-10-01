import type { RevisionDetails } from "@wiredex/api-client";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { statusKey } from "../status";
import { BomAddRow } from "./BomAddRow";
import { BomLineRow } from "./BomLineRow";
import { useBom } from "./bom";
import { bomCell, LineCells } from "./lineFields";
import { ShortageReport } from "./ShortageReport";

/**
 * A revision's bill of materials (requirement 11.1): a region named by its heading, with the
 * shortage report and a table of the lines, each with its designators, part, quantity, notes
 * and its part's stock status. A draft's table edits and removes each line in its own row and
 * ends with the row that adds one (requirements 11.2 to 11.6); any other revision shows its
 * lines without controls, and a note saying why (requirement 11.9). The table scrolls inside
 * its own box, so a phone never scrolls the page sideways (requirement 11.17).
 */
export function BomSection({ revision }: { revision: RevisionDetails }) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const bom = useBom(revision.id);
  const parts = new Map((bom.data?.report.parts ?? []).map((part) => [part.part_id, part]));
  const editable = bom.data?.editable ?? false;
  const lines = bom.data?.lines ?? [];

  return (
    <section aria-labelledby={headingId} className="grid min-w-0 gap-3">
      <h3 id={headingId} className="font-display text-xl font-semibold">
        {t("projects.bom.title")}
      </h3>

      {bom.isPending && <p className="text-muted">{t("projects.bom.loading")}</p>}
      {bom.isError && (
        <p role="alert" className="text-crit">
          {t("projects.bom.error")}
        </p>
      )}

      {bom.data && !editable && (
        <p className="text-sm text-muted">
          {t("projects.bom.locked", {
            status: t(statusKey(bom.data.status)).toLocaleLowerCase(i18n.language),
          })}
        </p>
      )}

      {bom.data && lines.length === 0 && !editable && (
        <p className="text-muted">{t("projects.bom.empty")}</p>
      )}

      {bom.data && lines.length > 0 && (
        <ShortageReport report={bom.data.report} rebuild={bom.data.status !== "draft"} />
      )}

      {bom.data && (lines.length > 0 || editable) && (
        <div
          // Positioned, so the table's screen-reader-only texts, placed absolutely, scroll and
          // clip with this box; otherwise they escape it and widen the page on a phone.
          className="relative overflow-x-auto"
        >
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
                {editable && (
                  <th scope="col" className={bomCell}>
                    <span className="sr-only">{t("projects.bom.columns.actions")}</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {lines.map((line) =>
                editable ? (
                  <BomLineRow
                    key={line.id}
                    revisionId={revision.id}
                    line={line}
                    part={parts.get(line.part_id)}
                  />
                ) : (
                  <tr key={line.id} className="border-b border-border">
                    <LineCells line={line} part={parts.get(line.part_id)} />
                  </tr>
                ),
              )}
              {editable && <BomAddRow revisionId={revision.id} />}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
