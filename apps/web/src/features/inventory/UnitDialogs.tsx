import type { LocationNode, RetireReason, UnitResponse } from "@wiredex/api-client";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { refusalMessage, useLocations } from "./inventory";
import { control, dialogPrimary, StockDialog } from "./StockDialog";
import { canonicalMac, useMoveUnit, useRelabelUnit, useRetireUnit } from "./units";

type UnitProps = { unit: UnitResponse; onClose: () => void };

/** Relabel a unit's serial and MAC, showing the canonical MAC once it validates (8.3, 8.5). */
export function RelabelUnitDialog({ unit, onClose }: UnitProps) {
  const { t } = useTranslation();
  const serialId = useId();
  const macId = useId();
  const relabel = useRelabelUnit();
  const [serial, setSerial] = useState(unit.serial ?? "");
  const [mac, setMac] = useState(unit.mac ?? "");

  const canonical = mac.trim() === "" ? null : canonicalMac(mac);
  const macInvalid = mac.trim() !== "" && canonical === null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (macInvalid) return;
    relabel.mutate(
      {
        unitId: unit.id,
        body: {
          serial: serial.trim() === "" ? null : serial.trim(),
          mac: mac.trim() === "" ? null : mac.trim(),
        },
      },
      { onSuccess: onClose },
    );
  }

  return (
    <StockDialog title={t("inventory.units.relabel.title", { code: unit.code })} onClose={onClose}>
      <form onSubmit={submit} className="grid gap-3">
        <div className="grid gap-1">
          <label htmlFor={serialId} className="text-sm font-medium">
            {t("inventory.units.serial")}
          </label>
          <input
            id={serialId}
            type="text"
            value={serial}
            onChange={(event) => setSerial(event.target.value)}
            className={control}
          />
        </div>
        <div className="grid gap-1">
          <label htmlFor={macId} className="text-sm font-medium">
            {t("inventory.units.mac")}
          </label>
          <input
            id={macId}
            type="text"
            value={mac}
            onChange={(event) => setMac(event.target.value)}
            aria-invalid={macInvalid}
            className={control}
          />
          {canonical && canonical !== mac.trim() && (
            <p className="text-sm text-muted">
              {t("inventory.units.macPreview", { mac: canonical })}
            </p>
          )}
          {macInvalid && (
            <p role="alert" className="text-sm text-crit">
              {t("inventory.units.macInvalid")}
            </p>
          )}
        </div>
        {relabel.isError && (
          <p role="alert" className="text-sm text-crit">
            {refusalMessage(relabel.error) ?? t("inventory.units.relabel.error")}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={relabel.isPending || macInvalid}
            className={dialogPrimary}
          >
            {t("inventory.units.relabel.confirm")}
          </button>
          <button type="button" onClick={onClose} className={control}>
            {t("inventory.units.cancel")}
          </button>
        </div>
      </form>
    </StockDialog>
  );
}

/** Move a unit to a destination location; the API refuses the same location (8.3). */
export function MoveUnitDialog({ unit, onClose }: UnitProps) {
  const { t } = useTranslation();
  const toId = useId();
  const locations = useLocations();
  const move = useMoveUnit();
  const [to, setTo] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (to === "") return;
    move.mutate({ unitId: unit.id, body: { to_location_id: to } }, { onSuccess: onClose });
  }

  return (
    <StockDialog title={t("inventory.units.move.title", { code: unit.code })} onClose={onClose}>
      <form onSubmit={submit} className="grid gap-3">
        <div className="grid gap-1">
          <label htmlFor={toId} className="text-sm font-medium">
            {t("inventory.units.move.to")}
          </label>
          <select
            id={toId}
            value={to}
            onChange={(event) => setTo(event.target.value)}
            className={control}
          >
            <option value="">{t("inventory.units.chooseLocation")}</option>
            {(locations.data ?? []).map((node: LocationNode) => (
              <option key={node.id} value={node.id}>
                {node.name} ({node.code})
              </option>
            ))}
          </select>
        </div>
        {move.isError && (
          <p role="alert" className="text-sm text-crit">
            {refusalMessage(move.error) ?? t("inventory.units.move.error")}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={move.isPending} className={dialogPrimary}>
            {t("inventory.units.move.confirm")}
          </button>
          <button type="button" onClick={onClose} className={control}>
            {t("inventory.units.cancel")}
          </button>
        </div>
      </form>
    </StockDialog>
  );
}

/** Retire a unit, choosing whether it was damaged or lost (8.3). */
export function RetireUnitDialog({ unit, onClose }: UnitProps) {
  const { t } = useTranslation();
  const reasonId = useId();
  const retire = useRetireUnit();
  const [reason, setReason] = useState<RetireReason>("damaged");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    retire.mutate({ unitId: unit.id, reason }, { onSuccess: onClose });
  }

  return (
    <StockDialog title={t("inventory.units.retire.title", { code: unit.code })} onClose={onClose}>
      <form onSubmit={submit} className="grid gap-3">
        <div className="grid gap-1">
          <label htmlFor={reasonId} className="text-sm font-medium">
            {t("inventory.units.retire.reason")}
          </label>
          <select
            id={reasonId}
            value={reason}
            onChange={(event) => setReason(event.target.value as RetireReason)}
            className={control}
          >
            <option value="damaged">{t("inventory.units.retire.reasons.damaged")}</option>
            <option value="lost">{t("inventory.units.retire.reasons.lost")}</option>
          </select>
        </div>
        {retire.isError && (
          <p role="alert" className="text-sm text-crit">
            {refusalMessage(retire.error) ?? t("inventory.units.retire.error")}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={retire.isPending} className={dialogPrimary}>
            {t("inventory.units.retire.confirm")}
          </button>
          <button type="button" onClick={onClose} className={control}>
            {t("inventory.units.cancel")}
          </button>
        </div>
      </form>
    </StockDialog>
  );
}
