import type { RevisionDetails } from "@wiredex/api-client";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { statusKey } from "../status";
import { NetRow } from "./NetRow";
import { netCell } from "./netCells";
import { useNetlist } from "./netlist";

/**
 * A revision's wiring (spec 11, requirement 10.1): a region named by its heading, with a
 * summary and a table of the nets, each with its colour, name, pins and notes. A revision that
 * isn't a draft shows its nets and says why they can't change (requirement 10.9). The table
 * scrolls inside its own box, so a phone never scrolls the page sideways (requirement 10.13).
 */
export function NetlistSection({ revision }: { revision: RevisionDetails }) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const netlist = useNetlist(revision.id);
  const nets = netlist.data?.nets ?? [];
  const editable = netlist.data?.editable ?? false;
  const summary = netlist.data?.summary;

  return (
    <section aria-labelledby={headingId} className="grid min-w-0 gap-3">
      <h3 id={headingId} className="font-display text-xl font-semibold">
        {t("projects.netlist.title")}
      </h3>

      {netlist.isPending && <p className="text-muted">{t("projects.netlist.loading")}</p>}
      {netlist.isError && (
        <p role="alert" className="text-crit">
          {t("projects.netlist.error")}
        </p>
      )}

      {netlist.data && !editable && (
        <p className="text-sm text-muted">
          {t("projects.netlist.locked", {
            status: t(statusKey(revision.status)).toLocaleLowerCase(i18n.language),
          })}
        </p>
      )}

      {summary && nets.length > 0 && (
        <p className="text-sm">
          {t("projects.netlist.summary", { nets: summary.nets, references: summary.references })}{" "}
          {summary.unchecked + summary.unresolved > 0 &&
            t("projects.netlist.summaryIssues", {
              unchecked: summary.unchecked,
              unresolved: summary.unresolved,
            })}
        </p>
      )}

      {netlist.data && nets.length === 0 && (
        <p className="text-muted">{t("projects.netlist.empty")}</p>
      )}

      {nets.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">{t("projects.netlist.caption")}</caption>
            <thead>
              <tr className="border-b border-border text-muted">
                <th scope="col" className={`${netCell} font-medium`}>
                  {t("projects.netlist.columns.color")}
                </th>
                <th scope="col" className={`${netCell} font-medium`}>
                  {t("projects.netlist.columns.name")}
                </th>
                <th scope="col" className={`${netCell} font-medium`}>
                  {t("projects.netlist.columns.pins")}
                </th>
                <th scope="col" className={`${netCell} font-medium`}>
                  {t("projects.netlist.columns.notes")}
                </th>
              </tr>
            </thead>
            <tbody>
              {nets.map((net) => (
                <NetRow key={net.id} net={net} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
