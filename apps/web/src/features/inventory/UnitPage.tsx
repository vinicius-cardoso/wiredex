import { Link, useNavigate } from "@tanstack/react-router";
import type { UnitResponse } from "@wiredex/api-client";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
import { FlashLogSection } from "../firmware/FlashLogSection";
import { RevisionLink } from "../projects/build/RevisionLink";
import { isHeld, refusalMessage } from "./inventory";
import { MoveUnitDialog, RelabelUnitDialog, RetireUnitDialog } from "./UnitDialogs";
import { useDeleteUnit, useUnit, useUnretireUnit } from "./units";

const action = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";

type OpenDialog = "relabel" | "move" | "retire" | null;

/**
 * One unit's page: its identity, its location, its status, and the actions on it — relabel,
 * move, retire, un-retire, and delete once it is retired (requirement 8.3).
 */
export function UnitPage({ unitId }: { unitId: string }) {
  const { t } = useTranslation();
  const unit = useUnit(unitId);

  return (
    <section className="grid max-w-2xl gap-4">
      <Link to="/units" className="text-sm text-muted hover:text-primary">
        {t("inventory.units.page.back")}
      </Link>
      {unit.isPending && <p className="text-muted">{t("inventory.units.page.loading")}</p>}
      {unit.isError && (
        <p role="alert" className="text-crit">
          {t("inventory.units.page.error")}
        </p>
      )}
      {unit.data && <UnitDetail unit={unit.data} />}
    </section>
  );
}

function UnitDetail({ unit }: { unit: UnitResponse }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState<OpenDialog>(null);
  const unretire = useUnretireUnit();
  const blank = t("inventory.units.blank");

  return (
    <>
      <h1 className="font-display text-3xl font-semibold tracking-tight">
        <span className="font-mono">{unit.code}</span>
      </h1>

      <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-[auto_1fr]">
        <Entry label={t("inventory.units.serial")} value={unit.serial ?? blank} />
        <Entry label={t("inventory.units.mac")} value={unit.mac ?? blank} mono />
        <Entry
          label={t("inventory.units.statusColumn")}
          value={t(`inventory.units.status.${unit.status}`)}
        />
        {isHeld(unit.status) && unit.revision_id ? (
          <Entry
            label={t("inventory.units.revision")}
            value={<RevisionLink id={unit.revision_id} />}
          />
        ) : (
          <Entry
            label={t("inventory.units.location")}
            value={unit.location ? `${unit.location.name} (${unit.location.code})` : blank}
          />
        )}
      </dl>

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => setOpen("relabel")} className={action}>
          {t("inventory.units.relabel.open")}
        </button>
        {/* A held unit offers only relabel: freeing it is a transition on the revision. */}
        {unit.status === "in_stock" && (
          <>
            <button type="button" onClick={() => setOpen("move")} className={action}>
              {t("inventory.units.move.open")}
            </button>
            <button type="button" onClick={() => setOpen("retire")} className={action}>
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
        <p role="alert" className="text-sm text-crit">
          {refusalMessage(unretire.error) ?? t("inventory.units.unretire.error")}
        </p>
      )}

      {unit.status === "retired" && <DeleteUnit unit={unit} />}

      {/* What the board runs and its flash log (spec 15, requirement 8.1). */}
      <FlashLogSection unit={unit} />

      {open === "relabel" && <RelabelUnitDialog unit={unit} onClose={() => setOpen(null)} />}
      {open === "move" && <MoveUnitDialog unit={unit} onClose={() => setOpen(null)} />}
      {open === "retire" && <RetireUnitDialog unit={unit} onClose={() => setOpen(null)} />}
    </>
  );
}

type EntryProps = { label: string; value: ReactNode; mono?: boolean };

function Entry({ label, value, mono }: EntryProps) {
  return (
    <>
      <dt className="text-sm text-muted">{label}</dt>
      <dd className={mono ? "font-mono" : undefined}>{value}</dd>
    </>
  );
}

/** Delete a retired unit, asking first; its ledger history stays (requirement 8.3). */
function DeleteUnit({ unit }: { unit: UnitResponse }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const remove = useDeleteUnit();
  const [asking, setAsking] = useState(false);

  if (!asking) {
    return (
      <button
        type="button"
        onClick={() => setAsking(true)}
        className="justify-self-start rounded-md border border-crit px-4 py-2 text-crit hover:bg-surface-2"
      >
        {t("inventory.units.delete.open")}
      </button>
    );
  }

  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm">
        {t("inventory.units.delete.question", { code: unit.code })}
      </legend>
      <p className="text-sm text-muted">{t("inventory.units.delete.hint")}</p>
      {remove.isError && (
        <p role="alert" className="text-sm text-crit">
          {refusalMessage(remove.error) ?? t("inventory.units.delete.error")}
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={remove.isPending}
          onClick={() =>
            remove.mutate(unit.id, { onSuccess: () => void navigate({ to: "/units" }) })
          }
          className="rounded-md bg-crit px-4 py-2 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {t("inventory.units.delete.confirm")}
        </button>
        <button type="button" onClick={() => setAsking(false)} className={action}>
          {t("inventory.units.delete.cancel")}
        </button>
      </div>
    </fieldset>
  );
}
