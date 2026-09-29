import { Link } from "@tanstack/react-router";
import type { UnitResponse } from "@wiredex/api-client";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { RevisionLink } from "../projects/build/RevisionLink";
import { isHeld, refusalMessage } from "./inventory";
import { MoveUnitDialog, RelabelUnitDialog, RetireUnitDialog } from "./UnitDialogs";
import { useUnitsOfPart, useUnretireUnit } from "./units";

const action = "rounded-md border border-border-strong px-2 py-1 text-xs hover:bg-surface-2";

type OpenDialog = { kind: "relabel" | "move" | "retire"; unit: UnitResponse } | null;

/**
 * The units of a part, beneath its stock breakdown: code, serial, MAC, status and location,
 * with relabel, move, retire and un-retire on each row (requirements 8.1, 8.3). The code
 * links to the unit's own page, where delete lives once it is retired.
 */
export function UnitsList({ partId }: { partId: string }) {
  const { t } = useTranslation();
  const units = useUnitsOfPart(partId);
  const [open, setOpen] = useState<OpenDialog>(null);

  return (
    <section aria-label={t("inventory.units.list")} className="grid gap-3">
      <h3 className="font-display text-lg font-semibold">{t("inventory.units.list")}</h3>

      {units.isPending && <p className="text-muted">{t("inventory.units.loading")}</p>}
      {units.isError && (
        <p role="alert" className="text-crit">
          {t("inventory.units.error")}
        </p>
      )}

      {units.data &&
        (units.data.length === 0 ? (
          <p className="text-muted">{t("inventory.units.none")}</p>
        ) : (
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">{t("inventory.units.list")}</caption>
            <thead>
              <tr className="border-b border-border text-muted">
                <th scope="col" className="py-2 pr-4 font-medium">
                  {t("inventory.units.codeColumn")}
                </th>
                <th scope="col" className="py-2 pr-4 font-medium">
                  {t("inventory.units.serialColumn")}
                </th>
                <th scope="col" className="py-2 pr-4 font-medium">
                  {t("inventory.units.macColumn")}
                </th>
                <th scope="col" className="py-2 pr-4 font-medium">
                  {t("inventory.units.statusColumn")}
                </th>
                <th scope="col" className="py-2 pr-4 font-medium">
                  {t("inventory.units.locationColumn")}
                </th>
                <th scope="col" className="py-2 font-medium">
                  {t("inventory.units.actionsColumn")}
                </th>
              </tr>
            </thead>
            <tbody>
              {units.data.map((unit) => (
                <UnitRow key={unit.id} unit={unit} onOpen={setOpen} />
              ))}
            </tbody>
          </table>
        ))}

      {open?.kind === "relabel" && (
        <RelabelUnitDialog unit={open.unit} onClose={() => setOpen(null)} />
      )}
      {open?.kind === "move" && <MoveUnitDialog unit={open.unit} onClose={() => setOpen(null)} />}
      {open?.kind === "retire" && (
        <RetireUnitDialog unit={open.unit} onClose={() => setOpen(null)} />
      )}
    </section>
  );
}

type RowProps = { unit: UnitResponse; onOpen: (open: OpenDialog) => void };

function UnitRow({ unit, onOpen }: RowProps) {
  const { t } = useTranslation();
  const unretire = useUnretireUnit();
  const blank = t("inventory.units.blank");

  return (
    <tr className="border-b border-border align-top">
      <th scope="row" className="py-2 pr-4 font-normal">
        <Link
          to="/units/$unitId"
          params={{ unitId: unit.id }}
          className="font-mono text-primary hover:underline"
        >
          {unit.code}
        </Link>
      </th>
      <td className="py-2 pr-4">{unit.serial ?? blank}</td>
      <td className="py-2 pr-4 font-mono">{unit.mac ?? blank}</td>
      <td className="py-2 pr-4">{t(`inventory.units.status.${unit.status}`)}</td>
      <td className="py-2 pr-4">
        {isHeld(unit.status) && unit.revision_id ? (
          <RevisionLink id={unit.revision_id} />
        ) : unit.location ? (
          unit.location.name
        ) : (
          blank
        )}
      </td>
      <td className="py-2">
        <div className="flex flex-wrap gap-1">
          <button
            type="button"
            onClick={() => onOpen({ kind: "relabel", unit })}
            className={action}
          >
            {t("inventory.units.relabel.open")}
          </button>
          {/* A held unit offers only relabel: freeing it is a transition on the revision. */}
          {unit.status === "in_stock" && (
            <>
              <button
                type="button"
                onClick={() => onOpen({ kind: "move", unit })}
                className={action}
              >
                {t("inventory.units.move.open")}
              </button>
              <button
                type="button"
                onClick={() => onOpen({ kind: "retire", unit })}
                className={action}
              >
                {t("inventory.units.retire.open")}
              </button>
            </>
          )}
          {unit.status === "retired" && (
            <button
              type="button"
              disabled={unretire.isPending}
              onClick={() => unretire.mutate(unit.id)}
              className={action}
            >
              {t("inventory.units.unretire.open")}
            </button>
          )}
        </div>
        {unretire.isError && (
          <p role="alert" className="pt-1 text-xs text-crit">
            {refusalMessage(unretire.error) ?? t("inventory.units.unretire.error")}
          </p>
        )}
      </td>
    </tr>
  );
}
