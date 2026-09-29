import type { RevisionDetails } from "@wiredex/api-client";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { statusKey } from "../status";
import { NetAddRow } from "./NetAddRow";
import { NetEditRow } from "./NetEditRow";
import { NetRow } from "./NetRow";
import { netCell } from "./netCells";
import { useNetlist } from "./netlist";

/**
 * A revision's wiring (spec 11, requirement 10.1): a region named by its heading, with a
 * summary and a table of the nets, each with its name, colour, pins and notes. A draft's table
 * edits and removes each net in its own row and ends with the row that adds one (requirements
 * 10.3 to 10.7); any other revision shows its nets and says why they can't change (10.9). The table
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

      {netlist.data && nets.length === 0 && !editable && (
        <p className="text-muted">{t("projects.netlist.empty")}</p>
      )}

      {(nets.length > 0 || editable) && (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">{t("projects.netlist.caption")}</caption>
            <thead>
              <tr className="border-b border-border text-muted">
                <th scope="col" className={`${netCell} font-medium`}>
                  {t("projects.netlist.columns.name")}
                </th>
                <th scope="col" className={`${netCell} font-medium`}>
                  {t("projects.netlist.columns.color")}
                </th>
                <th scope="col" className={`${netCell} font-medium`}>
                  {t("projects.netlist.columns.pins")}
                </th>
                <th scope="col" className={`${netCell} font-medium`}>
                  {t("projects.netlist.columns.notes")}
                </th>
                {editable && (
                  <th scope="col" className={netCell}>
                    <span className="sr-only">{t("projects.netlist.columns.actions")}</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {nets.map((net) =>
                editable && netlist.data ? (
                  <NetEditRow
                    key={net.id}
                    revisionId={revision.id}
                    net={net}
                    netlist={netlist.data}
                  />
                ) : (
                  <NetRow key={net.id} net={net} />
                ),
              )}
              {editable && netlist.data && (
                <NetAddRow revisionId={revision.id} netlist={netlist.data} />
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
