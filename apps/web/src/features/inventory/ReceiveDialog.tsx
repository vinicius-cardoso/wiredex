import type { LocationNode } from "@wiredex/api-client";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { refusalMessage, useLocations, useReceiveStock } from "./inventory";
import { control, dialogPrimary, StockDialog } from "./StockDialog";

type Props = { partId: string; onClose: () => void };

/** Receiving a positive quantity of a part into a location (requirement 9.3). */
export function ReceiveDialog({ partId, onClose }: Props) {
  const { t } = useTranslation();
  const locationId = useId();
  const quantityId = useId();
  const locations = useLocations();
  const receive = useReceiveStock();
  const [location, setLocation] = useState("");
  const [quantity, setQuantity] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const amount = Number(quantity);
    if (location === "" || !Number.isInteger(amount) || amount < 1) return;
    receive.mutate(
      { part_id: partId, location_id: location, quantity: amount },
      { onSuccess: onClose },
    );
  }

  return (
    <StockDialog title={t("inventory.stock.receive.title")} onClose={onClose}>
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
          <label htmlFor={quantityId} className="text-sm font-medium">
            {t("inventory.stock.quantity")}
          </label>
          <input
            id={quantityId}
            type="number"
            min={1}
            step={1}
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            className={control}
          />
        </div>
        {receive.isError && (
          <p role="alert" className="text-sm text-crit">
            {refusalMessage(receive.error) ?? t("inventory.stock.receive.error")}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={receive.isPending} className={dialogPrimary}>
            {t("inventory.stock.receive.confirm")}
          </button>
          <button type="button" onClick={onClose} className={control}>
            {t("inventory.stock.cancel")}
          </button>
        </div>
      </form>
    </StockDialog>
  );
}
