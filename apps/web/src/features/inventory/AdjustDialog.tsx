import type { LocationNode, MovementReason } from "@wiredex/api-client";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { refusalMessage, useAdjustStock, useLocations, usePartStock } from "./inventory";
import { control, dialogPrimary, StockDialog } from "./StockDialog";

type Props = { partId: string; onClose: () => void };

/** The reasons an adjust can carry, exactly the five the API accepts (requirement 4.4). */
const REASONS: MovementReason[] = ["recount", "damaged", "lost", "found", "correction"];

/**
 * Recounting a lot to an absolute counted quantity, with a reason (requirement 9.5). The
 * owner enters the number they counted, not a delta, and picks why the count changed; the
 * use case works out the signed change.
 */
export function AdjustDialog({ partId, onClose }: Props) {
  const { t } = useTranslation();
  const locationId = useId();
  const countedId = useId();
  const reasonId = useId();
  const locations = useLocations();
  const stock = usePartStock(partId);
  const adjust = useAdjustStock();
  const [location, setLocation] = useState("");
  const [counted, setCounted] = useState("");
  const [reason, setReason] = useState<MovementReason>("recount");

  // Reserved stock is a hard hold (requirement 7.1): a recount below what a build reserves at
  // this location is refused here, before the request goes, saying how many are reserved. The
  // API refuses it too; the check spares the round trip and reads the reason off the same
  // breakdown the page already shows.
  const reserved = stock.data?.breakdown.find((row) => row.location.id === location)?.reserved ?? 0;
  const amount = Number(counted);
  const belowReserved =
    location !== "" && counted !== "" && Number.isInteger(amount) && amount < reserved;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (location === "" || counted === "" || !Number.isInteger(amount) || amount < 0) return;
    if (belowReserved) return;
    adjust.mutate(
      { part_id: partId, location_id: location, counted: amount, reason },
      { onSuccess: onClose },
    );
  }

  return (
    <StockDialog title={t("inventory.stock.adjust.title")} onClose={onClose}>
      <form onSubmit={submit} className="grid gap-3">
        <div className="grid gap-1">
          <label htmlFor={locationId} className="text-sm font-medium">
            {t("inventory.stock.location")}
          </label>
          <select
            id={locationId}
            value={location}
            onChange={(event) => setLocation(event.target.value)}
            className={control}
          >
            <option value="">{t("inventory.stock.chooseLocation")}</option>
            {(locations.data ?? []).map((node: LocationNode) => (
              <option key={node.id} value={node.id}>
                {node.name} ({node.code})
              </option>
            ))}
          </select>
        </div>
        <div className="grid gap-1">
          <label htmlFor={countedId} className="text-sm font-medium">
            {t("inventory.stock.adjust.counted")}
          </label>
          <input
            id={countedId}
            type="number"
            min={0}
            step={1}
            value={counted}
            onChange={(event) => setCounted(event.target.value)}
            className={control}
          />
        </div>
        <div className="grid gap-1">
          <label htmlFor={reasonId} className="text-sm font-medium">
            {t("inventory.stock.adjust.reason")}
          </label>
          <select
            id={reasonId}
            value={reason}
            onChange={(event) => setReason(event.target.value as MovementReason)}
            className={control}
          >
            {REASONS.map((value) => (
              <option key={value} value={value}>
                {t(`inventory.stock.adjust.reasons.${value}`)}
              </option>
            ))}
          </select>
        </div>
        {belowReserved && (
          <p role="alert" className="text-sm text-crit">
            {t("inventory.stock.adjust.belowReserved", { count: reserved })}
          </p>
        )}
        {adjust.isError && (
          <p role="alert" className="text-sm text-crit">
            {refusalMessage(adjust.error) ?? t("inventory.stock.adjust.error")}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={adjust.isPending || belowReserved}
            className={dialogPrimary}
          >
            {t("inventory.stock.adjust.confirm")}
          </button>
          <button type="button" onClick={onClose} className={control}>
            {t("inventory.stock.cancel")}
          </button>
        </div>
      </form>
    </StockDialog>
  );
}
