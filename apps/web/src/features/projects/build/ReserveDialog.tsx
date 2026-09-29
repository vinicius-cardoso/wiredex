import type { BomPart } from "@wiredex/api-client";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { control, dialogPrimary, StockDialog } from "../../inventory/StockDialog";
import { useUnitsOfPart } from "../../inventory/units";
import { useBom } from "../bom/bom";
import { ShortageReport } from "../bom/ShortageReport";
import { SeverityLabel } from "../netlist/FindingsList";
import { errorsFirst, findingMessage } from "../netlist/findings";
import { useNetlist } from "../netlist/netlist";
import { LifecycleRefusal, useReserveRevision } from "./lifecycle";
import { refusalMessage } from "./refusal";

type Props = { revisionId: string; onClose: () => void };

/**
 * *Reserve parts* lists what will be reserved, names the consumables that won't be, and offers,
 * for each unit-tracked part, a checkbox per unit in stock — automatic by default (requirement
 * 13.2). Once a part's need is checked its other boxes disable; none checked means the
 * automatic choice, which the dialog says. A refusal stays in the dialog: for `short`, the
 * shortage report with each short and unknown part linking to its page; for a unit refusal, the
 * unit's code (requirement 13.3). The wiring's findings are listed above *Reserve* as
 * warnings, and never stop it (spec 12, requirement 6.1).
 */
export function ReserveDialog({ revisionId, onClose }: Props) {
  const { t, i18n } = useTranslation();
  const bom = useBom(revisionId);
  const findings = useNetlist(revisionId).data?.findings ?? [];
  const reserve = useReserveRevision();
  const [checked, setChecked] = useState<Set<string>>(new Set());

  const parts = bom.data?.report.parts ?? [];
  const stocked = parts.filter((part) => part.part && !part.part.not_stocked);
  const consumables = parts.filter((part) => part.part?.not_stocked);
  const tracked = stocked.filter((part) => part.part?.tracked_individually);

  const refusal = reserve.error instanceof LifecycleRefusal ? reserve.error : null;

  function toggle(unitId: string) {
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(unitId)) next.delete(unitId);
      else next.add(unitId);
      return next;
    });
  }

  function send() {
    reserve.mutate({ revisionId, units: [...checked] }, { onSuccess: onClose });
  }

  return (
    <StockDialog title={t("projects.lifecycle.reserve.title")} onClose={onClose} wide>
      <div className="grid gap-4">
        {bom.isPending && <p className="text-muted">{t("projects.lifecycle.reserve.loading")}</p>}
        {bom.isError && (
          <p role="alert" className="text-crit">
            {t("projects.lifecycle.reserve.loadError")}
          </p>
        )}

        {bom.data && (
          <>
            <section aria-labelledby={`${revisionId}-will`} className="grid gap-2">
              <h4 id={`${revisionId}-will`} className="font-semibold">
                {t("projects.lifecycle.reserve.willReserve")}
              </h4>
              {stocked.length === 0 ? (
                <p className="text-sm text-muted">
                  {t("projects.lifecycle.reserve.nothingStocked")}
                </p>
              ) : (
                <ul className="grid gap-1 text-sm">
                  {stocked.map((part) => (
                    <li key={part.part_id} className="flex justify-between gap-3">
                      <span>{part.part?.name}</span>
                      <span className="text-muted">
                        {t("projects.lifecycle.reserve.need", { count: part.need })}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {consumables.length > 0 && (
              <section aria-labelledby={`${revisionId}-consumables`} className="grid gap-1">
                <h4 id={`${revisionId}-consumables`} className="font-semibold">
                  {t("projects.lifecycle.reserve.consumables")}
                </h4>
                <p className="text-sm text-muted">
                  {consumables.map((part) => part.part?.name).join(", ")}
                </p>
              </section>
            )}

            {tracked.length > 0 && (
              <section aria-labelledby={`${revisionId}-units`} className="grid gap-3">
                <h4 id={`${revisionId}-units`} className="font-semibold">
                  {t("projects.lifecycle.reserve.chooseUnits")}
                </h4>
                <p className="text-sm text-muted">{t("projects.lifecycle.reserve.automatic")}</p>
                {tracked.map((part) => (
                  <PartUnits key={part.part_id} part={part} checked={checked} onToggle={toggle} />
                ))}
              </section>
            )}

            {refusal?.code === "short" && refusal.report && (
              <ShortageReport report={refusal.report} />
            )}
            {reserve.isError && refusal?.code !== "short" && (
              <p role="alert" className="text-sm text-crit">
                {refusalMessage(t, refusal)}
              </p>
            )}

            {findings.length > 0 && (
              <section aria-labelledby={`${revisionId}-wiring`} className="grid gap-1">
                <h4 id={`${revisionId}-wiring`} className="font-semibold text-warn">
                  {t("projects.lifecycle.reserve.wiring")}
                </h4>
                <p className="text-sm text-muted">{t("projects.lifecycle.reserve.wiringNote")}</p>
                <ul className="grid gap-1 text-sm">
                  {errorsFirst(findings).map((finding) => (
                    <li
                      key={`${finding.code}:${finding.net_ids.join(",")}:${finding.refs.join(",")}`}
                      className="flex min-w-0 flex-wrap items-baseline gap-x-2"
                    >
                      <SeverityLabel severity={finding.severity} />
                      <span className="min-w-0 break-words">
                        {findingMessage(t, i18n.language, finding)}{" "}
                        {finding.nets.length > 0 &&
                          `${t("projects.netlist.findings.nets")} ${finding.nets.join(", ")}`}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={reserve.isPending}
                onClick={send}
                className={dialogPrimary}
              >
                {t("projects.lifecycle.reserve.confirm")}
              </button>
              <button type="button" onClick={onClose} className={control}>
                {t("projects.lifecycle.reserve.cancel")}
              </button>
            </div>
          </>
        )}
      </div>
    </StockDialog>
  );
}

type PartUnitsProps = {
  part: BomPart;
  checked: Set<string>;
  onToggle: (unitId: string) => void;
};

/**
 * One unit-tracked part's in-stock units, each a checkbox labelled by its code. Once as many
 * as the part's need are checked, the rest disable, so a reserve never names more than the need
 * (requirement 13.2). The list scrolls inside its own box, so a phone never scrolls the page
 * sideways (requirement 13.16).
 */
function PartUnits({ part, checked, onToggle }: PartUnitsProps) {
  const { t } = useTranslation();
  const units = useUnitsOfPart(part.part_id);
  const inStock = useMemo(
    () => (units.data ?? []).filter((unit) => unit.status === "in_stock"),
    [units.data],
  );
  const chosen = inStock.filter((unit) => checked.has(unit.id)).length;
  const atNeed = chosen >= part.need;

  return (
    <fieldset className="grid min-w-0 gap-1">
      <legend className="text-sm font-medium">
        {t("projects.lifecycle.reserve.unitsOf", { part: part.part?.name, count: part.need })}
      </legend>
      {inStock.length === 0 ? (
        <p className="text-sm text-muted">{t("projects.lifecycle.reserve.noUnits")}</p>
      ) : (
        <ul className="grid max-h-48 gap-1 overflow-y-auto">
          {inStock.map((unit) => {
            const isChecked = checked.has(unit.id);
            return (
              <li key={unit.id}>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={isChecked}
                    disabled={!isChecked && atNeed}
                    onChange={() => onToggle(unit.id)}
                    className="size-4 rounded border-border-strong"
                  />
                  <span className="font-mono">{unit.code}</span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </fieldset>
  );
}
