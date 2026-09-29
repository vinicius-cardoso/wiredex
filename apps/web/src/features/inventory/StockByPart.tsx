import { useState } from "react";
import { useTranslation } from "react-i18next";
import { AdjustDialog } from "./AdjustDialog";
import { usePartStock } from "./inventory";
import { MoveDialog } from "./MoveDialog";
import { PartHoldings } from "./PartHoldings";
import { ReceiveDialog } from "./ReceiveDialog";
import { ReceiveUnitsDialog } from "./ReceiveUnitsDialog";
import { UnitsList } from "./UnitsList";

const action = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";

type OpenDialog = "receive" | "adjust" | "move" | null;

type Props = { partId: string; unitTracked?: boolean; notStocked?: boolean };

/**
 * A part's stock on its page: the totals and where it sits, on hand, reserved and available
 * per location and in total, with the receive, adjust and move dialogs (requirements 7.3, 9.3,
 * 13.8). A change made through a dialog invalidates both the inventory and catalog caches, so
 * the totals and breakdown update in place (9.4). The breakdown table, now three number
 * columns wide, scrolls inside its own box so a phone never scrolls the page sideways
 * (requirement 13.16), and the builds holding the part sit beneath it (requirement 13.8).
 *
 * A unit-tracked part receives units, not a loose lot count, so it shows *Receive units* in
 * place of *Receive* and lists its units beneath the breakdown (requirement 8.1). It has no
 * *Adjust* or *Move* either: the API refuses both for it, and its units are retired and moved
 * one by one from the list.
 *
 * A consumable, whose category resolves not stocked, is never received (09's requirement
 * 2.1): it says so and offers no receipt. What it held before the flag was set still works
 * (2.3), so *Adjust* and *Move* stay while it holds a lot, and a tracked one still lists its
 * units (11.11). Both flags are the part's own, passed down by the part page.
 */
export function StockByPart({ partId, unitTracked = false, notStocked = false }: Props) {
  const { t } = useTranslation();
  const stock = usePartStock(partId);
  const [open, setOpen] = useState<OpenDialog>(null);
  // A lot at zero is still a lot: recounting where the part was kept is recounting held
  // stock, which the API allows (09's decision 4).
  const holdsStock = (stock.data?.breakdown.length ?? 0) > 0;
  const receives = !notStocked;
  const recountsAndMoves = !unitTracked && (!notStocked || holdsStock);

  return (
    <section aria-label={t("inventory.stock.title")} className="grid min-w-0 gap-3">
      <h2 className="font-display text-xl font-semibold">{t("inventory.stock.title")}</h2>
      {notStocked && (
        <p className="max-w-prose text-muted">
          {t("inventory.stock.notStocked")}
          {holdsStock && !unitTracked && ` ${t("inventory.stock.notStockedHeld")}`}
        </p>
      )}

      {stock.isPending && <p className="text-muted">{t("inventory.stock.loading")}</p>}
      {stock.isError && (
        <p role="alert" className="text-crit">
          {t("inventory.stock.error")}
        </p>
      )}

      {stock.data && (
        <>
          <p className="flex flex-wrap gap-x-2 text-lg">
            <span>{t("inventory.stock.total", { count: stock.data.total })}</span>
            <span className="text-muted">·</span>
            <span className="text-muted">
              {t("inventory.stock.totalReserved", { count: stock.data.reserved })}
            </span>
            <span className="text-muted">·</span>
            <span className="text-muted">
              {t("inventory.stock.totalAvailable", { count: stock.data.available })}
            </span>
          </p>
          {stock.data.breakdown.length === 0 ? (
            <p className="text-muted">{t("inventory.stock.none")}</p>
          ) : (
            <div className="max-w-md overflow-x-auto">
              <table className="w-full border-collapse text-left text-sm">
                <caption className="sr-only">{t("inventory.stock.breakdown")}</caption>
                <thead>
                  <tr className="border-b border-border text-muted">
                    <th scope="col" className="py-2 pr-4 font-medium">
                      {t("inventory.stock.locationColumn")}
                    </th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">
                      {t("inventory.stock.onHand")}
                    </th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">
                      {t("inventory.stock.reservedColumn")}
                    </th>
                    <th scope="col" className="py-2 text-right font-medium">
                      {t("inventory.stock.availableColumn")}
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
                      <td className="py-2 pr-4 text-right tabular-nums">{row.on_hand}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{row.reserved}</td>
                      <td className="py-2 text-right tabular-nums">{row.available}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {(receives || recountsAndMoves) && (
        <div className="flex flex-wrap gap-2">
          {receives && (
            <button type="button" onClick={() => setOpen("receive")} className={action}>
              {unitTracked ? t("inventory.units.receive.open") : t("inventory.stock.receive.open")}
            </button>
          )}
          {recountsAndMoves && (
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
      )}

      {open === "receive" &&
        (unitTracked ? (
          <ReceiveUnitsDialog partId={partId} onClose={() => setOpen(null)} />
        ) : (
          <ReceiveDialog partId={partId} onClose={() => setOpen(null)} />
        ))}
      {open === "adjust" && <AdjustDialog partId={partId} onClose={() => setOpen(null)} />}
      {open === "move" && <MoveDialog partId={partId} onClose={() => setOpen(null)} />}

      <PartHoldings partId={partId} />

      {unitTracked && <UnitsList partId={partId} />}
    </section>
  );
}
