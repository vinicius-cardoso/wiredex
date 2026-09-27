import { useState } from "react";
import { useTranslation } from "react-i18next";
import { AdjustDialog } from "./AdjustDialog";
import { usePartStock } from "./inventory";
import { MoveDialog } from "./MoveDialog";
import { ReceiveDialog } from "./ReceiveDialog";
import { ReceiveUnitsDialog } from "./ReceiveUnitsDialog";
import { UnitsList } from "./UnitsList";

const action = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";

type OpenDialog = "receive" | "adjust" | "move" | null;

type Props = { partId: string; unitTracked?: boolean };

/**
 * A part's stock on its page: the total on hand and where it sits, with the receive, adjust
 * and move dialogs (requirements 7.3, 9.3). A change made through a dialog invalidates both
 * the inventory and catalog caches, so the total and breakdown update in place (9.4).
 *
 * A unit-tracked part receives units, not a loose lot count, so it shows *Receive units* in
 * place of *Receive* and lists its units beneath the breakdown (requirement 8.1). It has no
 * *Adjust* or *Move* either: the API refuses both for it, and its units are retired and moved
 * one by one from the list. The category's resolved tracking flag is read on the part page
 * and passed down here.
 */
export function StockByPart({ partId, unitTracked = false }: Props) {
  const { t } = useTranslation();
  const stock = usePartStock(partId);
  const [open, setOpen] = useState<OpenDialog>(null);

  return (
    <section aria-label={t("inventory.stock.title")} className="grid gap-3">
      <h2 className="font-display text-xl font-semibold">{t("inventory.stock.title")}</h2>

      {stock.isPending && <p className="text-muted">{t("inventory.stock.loading")}</p>}
      {stock.isError && (
        <p role="alert" className="text-crit">
          {t("inventory.stock.error")}
        </p>
      )}

      {stock.data && (
        <>
          <p className="text-lg">{t("inventory.stock.total", { count: stock.data.total })}</p>
          {stock.data.breakdown.length === 0 ? (
            <p className="text-muted">{t("inventory.stock.none")}</p>
          ) : (
            <table className="w-full max-w-md border-collapse text-left text-sm">
              <caption className="sr-only">{t("inventory.stock.breakdown")}</caption>
              <thead>
                <tr className="border-b border-border text-muted">
                  <th scope="col" className="py-2 pr-4 font-medium">
                    {t("inventory.stock.locationColumn")}
                  </th>
                  <th scope="col" className="py-2 font-medium">
                    {t("inventory.stock.onHand")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {stock.data.breakdown.map((row) => (
                  <tr key={row.location.id} className="border-b border-border">
                    <th scope="row" className="py-2 pr-4 font-normal">
                      {row.location.name}{" "}
                      <span className="font-mono text-muted">{row.location.code}</span>
                    </th>
                    <td className="py-2">{row.on_hand}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => setOpen("receive")} className={action}>
          {unitTracked ? t("inventory.units.receive.open") : t("inventory.stock.receive.open")}
        </button>
        {!unitTracked && (
          <>
            <button type="button" onClick={() => setOpen("adjust")} className={action}>
              {t("inventory.stock.adjust.open")}
            </button>
            <button type="button" onClick={() => setOpen("move")} className={action}>
              {t("inventory.stock.move.open")}
            </button>
          </>
        )}
      </div>

      {open === "receive" &&
        (unitTracked ? (
          <ReceiveUnitsDialog partId={partId} onClose={() => setOpen(null)} />
        ) : (
          <ReceiveDialog partId={partId} onClose={() => setOpen(null)} />
        ))}
      {open === "adjust" && <AdjustDialog partId={partId} onClose={() => setOpen(null)} />}
      {open === "move" && <MoveDialog partId={partId} onClose={() => setOpen(null)} />}

      {unitTracked && <UnitsList partId={partId} />}
    </section>
  );
}
