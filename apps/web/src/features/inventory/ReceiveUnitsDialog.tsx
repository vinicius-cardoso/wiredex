import type { LocationNode, NewUnitBody } from "@wiredex/api-client";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { refusalMessage, useLocations } from "./inventory";
import { control, dialogPrimary, StockDialog } from "./StockDialog";
import { canonicalMac, useReceiveUnits } from "./units";

type Props = { partId: string; onClose: () => void };

type UnitRow = { serial: string; mac: string };

const MAX_QUANTITY = 100;

/**
 * Receiving N units of a unit-tracked part into a location: a quantity, a destination, and an
 * optional serial and MAC per unit as a small repeating row. On success it shows the minted
 * codes rather than closing at once, so the owner can note them down (requirements 8.1, 8.2).
 */
export function ReceiveUnitsDialog({ partId, onClose }: Props) {
  const { t } = useTranslation();
  const locationId = useId();
  const quantityId = useId();
  const locations = useLocations();
  const receive = useReceiveUnits();
  const [location, setLocation] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [rows, setRows] = useState<UnitRow[]>([{ serial: "", mac: "" }]);
  const [minted, setMinted] = useState<string[] | null>(null);

  // The quantity is what the owner typed; the rows follow it, so N is one serial/MAC row per
  // unit. A quantity outside 1..MAX leaves the rows as they were, keeping any typed values.
  function changeQuantity(typed: string) {
    setQuantity(typed);
    const next = Number(typed);
    if (!Number.isInteger(next) || next < 1 || next > MAX_QUANTITY) return;
    setRows((current) => {
      if (next === current.length) return current;
      if (next < current.length) return current.slice(0, next);
      return [...current, ...Array.from({ length: next - current.length }, emptyRow)];
    });
  }

  function editRow(index: number, patch: Partial<UnitRow>) {
    setRows((current) => current.map((row, at) => (at === index ? { ...row, ...patch } : row)));
  }

  // A typed MAC that isn't yet six hex octets blocks the receive, so a malformed one never
  // reaches the API; a blank one is fine (requirement 8.5).
  const macInvalid = rows.some((row) => row.mac.trim() !== "" && canonicalMac(row.mac) === null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (location === "" || macInvalid) return;
    const units: NewUnitBody[] = rows.map((row) => ({
      serial: row.serial.trim() === "" ? null : row.serial.trim(),
      mac: row.mac.trim() === "" ? null : row.mac.trim(),
    }));
    receive.mutate(
      { part_id: partId, location_id: location, units },
      { onSuccess: (result) => setMinted(result.units.map((unit) => unit.code)) },
    );
  }

  if (minted) {
    return (
      <StockDialog title={t("inventory.units.receive.title")} onClose={onClose}>
        <div className="grid gap-3">
          <p>{t("inventory.units.receive.minted", { codes: minted.join(", ") })}</p>
          <ul className="grid gap-1 font-mono text-sm">
            {minted.map((code) => (
              <li key={code}>{code}</li>
            ))}
          </ul>
          <button type="button" onClick={onClose} className={dialogPrimary}>
            {t("inventory.units.cancel")}
          </button>
        </div>
      </StockDialog>
    );
  }

  return (
    <StockDialog title={t("inventory.units.receive.title")} onClose={onClose}>
      <form onSubmit={submit} className="grid gap-3">
        <p className="text-sm text-muted">{t("inventory.units.receive.intro")}</p>
        <div className="grid gap-1">
          <label htmlFor={locationId} className="text-sm font-medium">
            {t("inventory.units.location")}
          </label>
          <select
            id={locationId}
            value={location}
            onChange={(event) => setLocation(event.target.value)}
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
        <div className="grid gap-1">
          <label htmlFor={quantityId} className="text-sm font-medium">
            {t("inventory.units.quantity")}
          </label>
          <input
            id={quantityId}
            type="number"
            min={1}
            max={MAX_QUANTITY}
            step={1}
            value={quantity}
            onChange={(event) => changeQuantity(event.target.value)}
            className={control}
          />
        </div>

        <ul className="grid gap-3">
          {rows.map((row, index) => (
            // The rows are positional and never reordered, so the index is a stable key.
            // biome-ignore lint/suspicious/noArrayIndexKey: positional, never reordered
            <li key={index}>
              <UnitFields index={index} row={row} onChange={(patch) => editRow(index, patch)} />
            </li>
          ))}
        </ul>

        {receive.isError && (
          <p role="alert" className="text-sm text-crit">
            {refusalMessage(receive.error) ?? t("inventory.units.receive.error")}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={receive.isPending || macInvalid}
            className={dialogPrimary}
          >
            {t("inventory.units.receive.confirm")}
          </button>
          <button type="button" onClick={onClose} className={control}>
            {t("inventory.units.cancel")}
          </button>
        </div>
      </form>
    </StockDialog>
  );
}

type FieldsProps = { index: number; row: UnitRow; onChange: (patch: Partial<UnitRow>) => void };

/** One unit's optional serial and MAC, with the canonical MAC shown once it validates. */
function UnitFields({ index, row, onChange }: FieldsProps) {
  const { t } = useTranslation();
  const serialId = useId();
  const macId = useId();
  const canonical = row.mac.trim() === "" ? null : canonicalMac(row.mac);
  const invalid = row.mac.trim() !== "" && canonical === null;

  return (
    <fieldset className="grid gap-2 rounded-md border border-border p-3">
      <legend className="px-1 text-sm text-muted">
        {t("inventory.units.unit", { index: index + 1 })}
      </legend>
      <div className="grid gap-1">
        <label htmlFor={serialId} className="text-sm font-medium">
          {t("inventory.units.serial")}
        </label>
        <input
          id={serialId}
          type="text"
          value={row.serial}
          onChange={(event) => onChange({ serial: event.target.value })}
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
          value={row.mac}
          onChange={(event) => onChange({ mac: event.target.value })}
          aria-invalid={invalid}
          className={control}
        />
        {canonical && canonical !== row.mac.trim() && (
          <p className="text-sm text-muted">
            {t("inventory.units.macPreview", { mac: canonical })}
          </p>
        )}
        {invalid && (
          <p role="alert" className="text-sm text-crit">
            {t("inventory.units.macInvalid")}
          </p>
        )}
      </div>
    </fieldset>
  );
}

function emptyRow(): UnitRow {
  return { serial: "", mac: "" };
}
