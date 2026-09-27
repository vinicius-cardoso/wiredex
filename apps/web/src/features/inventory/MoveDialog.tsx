import type { LocationNode } from "@wiredex/api-client";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { refusalMessage, useLocations, useMoveStock } from "./inventory";
import { control, dialogPrimary, StockDialog } from "./StockDialog";

type Props = { partId: string; onClose: () => void };

/** Moving a quantity of a part from one location to another (requirement 9.3). */
export function MoveDialog({ partId, onClose }: Props) {
  const { t } = useTranslation();
  const fromId = useId();
  const toId = useId();
  const quantityId = useId();
  const locations = useLocations();
  const move = useMoveStock();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [quantity, setQuantity] = useState("");

  const nodes = locations.data ?? [];
  const sameLocation = from !== "" && from === to;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const amount = Number(quantity);
    if (from === "" || to === "" || sameLocation) return;
    if (!Number.isInteger(amount) || amount < 1) return;
    move.mutate(
      { part_id: partId, from_location_id: from, to_location_id: to, quantity: amount },
      { onSuccess: onClose },
    );
  }

  return (
    <StockDialog title={t("inventory.stock.move.title")} onClose={onClose}>
      <form onSubmit={submit} className="grid gap-3">
        <div className="grid gap-1">
          <label htmlFor={fromId} className="text-sm font-medium">
            {t("inventory.stock.move.from")}
          </label>
          <select
            id={fromId}
            value={from}
            onChange={(event) => setFrom(event.target.value)}
            className={control}
          >
            <option value="">{t("inventory.stock.chooseLocation")}</option>
            {nodes.map((node: LocationNode) => (
              <option key={node.id} value={node.id}>
                {node.name} ({node.code})
              </option>
            ))}
          </select>
        </div>
        <div className="grid gap-1">
          <label htmlFor={toId} className="text-sm font-medium">
            {t("inventory.stock.move.to")}
          </label>
          <select
            id={toId}
            value={to}
            onChange={(event) => setTo(event.target.value)}
            className={control}
          >
            <option value="">{t("inventory.stock.chooseLocation")}</option>
            {nodes.map((node: LocationNode) => (
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
        {sameLocation && (
          <p role="alert" className="text-sm text-crit">
            {t("inventory.stock.move.sameLocation")}
          </p>
        )}
        {move.isError && (
          <p role="alert" className="text-sm text-crit">
            {refusalMessage(move.error) ?? t("inventory.stock.move.error")}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={move.isPending || sameLocation} className={dialogPrimary}>
            {t("inventory.stock.move.confirm")}
          </button>
          <button type="button" onClick={onClose} className={control}>
            {t("inventory.stock.cancel")}
          </button>
        </div>
      </form>
    </StockDialog>
  );
}
