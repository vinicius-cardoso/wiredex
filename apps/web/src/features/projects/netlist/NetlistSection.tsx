import { useNavigate, useSearch } from "@tanstack/react-router";
import type { RevisionDetails } from "@wiredex/api-client";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Block, type BlockSpan, StackedTable } from "../../../shared/ui/block";
import { statusKey } from "../status";
import { FindingsList } from "./FindingsList";
import { severityByRef } from "./findings";
import { NetAddRow } from "./NetAddRow";
import { NetEditRow } from "./NetEditRow";
import { NetFilter } from "./NetFilter";
import { NetRow } from "./NetRow";
import { netCell } from "./netCells";
import { useNetlist } from "./netlist";
import { WiringDiagram } from "./WiringDiagram";
import { netsLitBy, WiringContext, type WiringFocus } from "./wiringFocus";

/**
 * A revision's wiring (spec 11, requirement 10.1): a region named by its heading, with a
 * summary, the nets drawn as a diagram, and a table of the nets, each with its name, colour, pins and notes. A draft's table
 * edits and removes each net in its own row and ends with the row that adds one (requirements
 * 10.3 to 10.7); any other revision shows its nets and says why they can't change (10.9). Where
 * its box is narrow the table reflows into a card per net, so a phone never scrolls the page
 * sideways (requirement 10.13).
 * The diagram draws the nets its toggles leave on; the ones turned off are in the address
 * (`?hide=`), so a filtered view can be linked to, and stay in the table. Pointing at a net in
 * the diagram, its toggle or its row lights it in all three.
 * Spec 12's findings follow the table, and mark the chips they name (requirements 10.1, 10.2).
 */
export function NetlistSection({
  revision,
  span,
}: {
  revision: RevisionDetails;
  span?: BlockSpan | undefined;
}) {
  const { t, i18n } = useTranslation();
  const netlist = useNetlist(revision.id);
  const nets = netlist.data?.nets ?? [];
  const editable = netlist.data?.editable ?? false;
  const summary = netlist.data?.summary;
  const findings = netlist.data?.findings;
  const severities = useMemo(() => severityByRef(findings ?? []), [findings]);

  const navigate = useNavigate();
  const hide = useSearch({ strict: false, select: (search) => hiddenIn(search) });
  const hidden = useMemo(() => new Set(hide), [hide]);
  const drawn = useMemo(
    () => (netlist.data?.nets ?? []).filter((net) => !hidden.has(net.name)),
    [netlist.data, hidden],
  );
  function setHidden(names: string[]) {
    void navigate({
      to: ".",
      // The page stays where it is; only the address remembers.
      search: (search: Record<string, unknown>) => ({
        ...search,
        hide: names.length > 0 ? names : undefined,
      }),
      replace: true,
      resetScroll: false,
    } as never);
  }

  const [hovered, setHovered] = useState<WiringFocus | null>(null);
  const [held, setHeld] = useState<WiringFocus | null>(null);
  const wiring = useMemo(
    () => ({
      lit: netsLitBy(hovered ?? held, netlist.data?.nets ?? []),
      held,
      hover: setHovered,
      hold: setHeld,
    }),
    [hovered, held, netlist.data],
  );

  return (
    <WiringContext value={wiring}>
      <Block level={3} span={span} title={t("projects.netlist.title")}>
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
              })}{" "}
            {t("projects.netlist.summaryFindings", {
              errors: t("projects.netlist.findings.errors", { count: summary.errors }),
              warnings: t("projects.netlist.findings.warnings", { count: summary.warnings }),
            })}
          </p>
        )}

        {nets.some((net) => net.pins.length > 1) && (
          <>
            <NetFilter nets={nets} hidden={hidden} onChange={setHidden} />
            {drawn.length === 0 && (
              <p className="text-sm text-muted">{t("projects.netlist.filter.nothing")}</p>
            )}
            <WiringDiagram nets={drawn} />
          </>
        )}

        {netlist.data && nets.length === 0 && !editable && (
          <p className="text-muted">{t("projects.netlist.empty")}</p>
        )}

        {(nets.length > 0 || editable) && (
          // The pin chips and a draft's fields need a laptop's width; narrower, each net is a card.
          <StackedTable below="lg">
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
                      severities={severities}
                    />
                  ) : (
                    <NetRow key={net.id} net={net} severities={severities} />
                  ),
                )}
                {editable && netlist.data && (
                  <NetAddRow revisionId={revision.id} netlist={netlist.data} />
                )}
              </tbody>
            </table>
          </StackedTable>
        )}

        {findings && nets.length > 0 && <FindingsList findings={findings} />}
      </Block>
    </WiringContext>
  );
}

/** The net names `?hide=` lists; anything else in its place hides nothing. */
function hiddenIn(search: Record<string, unknown>): string[] {
  const hide = search.hide;
  const names = Array.isArray(hide) ? hide : typeof hide === "string" ? [hide] : [];
  return names.filter((name): name is string => typeof name === "string");
}
