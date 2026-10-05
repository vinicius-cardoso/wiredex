import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Block, type BlockSpan, StackedTable } from "../../shared/ui/block";
import { AdjustDialog } from "./AdjustDialog";
import { usePartStock } from "./inventory";
import { MoveDialog } from "./MoveDialog";
import { PartHoldings } from "./PartHoldings";
import { ReceiveDialog } from "./ReceiveDialog";
import { ReceiveUnitsDialog } from "./ReceiveUnitsDialog";

const action = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";

type OpenDialog = "receive" | "adjust" | "move" | null;

type Props = {
  partId: string;
  unitTracked?: boolean;
  notStocked?: boolean;
  span?: BlockSpan | undefined;
};

/**
 * A part's stock block on its page: the totals and where it sits, on hand, reserved and
 * available per location and in total, with the receive, adjust and move dialogs
 * (requirements 7.3, 9.3, 13.8). A change made through a dialog invalidates both the
 * inventory and catalog caches, so the totals and breakdown update in place (9.4). The
 * breakdown table turns into one card per location when the block is narrow, so a phone
 * never scrolls the page sideways (requirement 13.16), and the builds holding the part sit
 * beneath it (requirement 13.8).
 *
 * A unit-tracked part receives units, not a loose lot count, so it shows *Receive units* in
 * place of *Receive* (requirement 8.1); the part page lists its units in a block of their
 * own. It has no *Adjust* or *Move* either: the API refuses both for it, and its units are
 * retired and moved one by one from that list.
 *
 * A consumable, whose category resolves not stocked, is never received (09's requirement
 * 2.1): it says so and offers no receipt. What it held before the flag was set still works
 * (2.3), so *Adjust* and *Move* stay while it holds a lot. Both flags are the part's own,
 * passed down by the part page.
 */
export function StockByPart({ partId, unitTracked = false, notStocked = false, span }: Props) {
  const { t } = useTranslation();
  const stock = usePartStock(partId);
  const [open, setOpen] = useState<OpenDialog>(null);
  // A lot at zero is still a lot: recounting where the part was kept is recounting held
  // stock, which the API allows (09's decision 4).
  const holdsStock = (stock.data?.breakdown.length ?? 0) > 0;
  const receives = !notStocked;
  const recountsAndMoves = !unitTracked && (!notStocked || holdsStock);

  return (
    <Block title={t("inventory.stock.title")} span={span}>
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
            <StackedTable below="xs">
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
                      <td
                        data-label={t("inventory.stock.onHand")}
                        className="py-2 pr-4 text-right tabular-nums"
                      >
                        {row.on_hand}
                      </td>
                      <td
                        data-label={t("inventory.stock.reservedColumn")}
                        className="py-2 pr-4 text-right tabular-nums"
                      >
                        {row.reserved}
                      </td>
                      <td
                        data-label={t("inventory.stock.availableColumn")}
                        className="py-2 text-right tabular-nums"
                      >
                        {row.available}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </StackedTable>
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
    </Block>
  );
}
