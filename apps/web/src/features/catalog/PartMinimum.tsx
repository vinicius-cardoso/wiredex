import { Link } from "@tanstack/react-router";
import type { PartDetails } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { usePartStock } from "../inventory/inventory";
import { usePreferences } from "../settings/preferences";

/**
 * A part's minimum stock on its page (spec 24): the number it is held to and the category it
 * comes from when it isn't the part's own, and, when the part is below it, by how much, counted
 * the way the workspace chose. Not shown for a part nobody stocks.
 */
export function PartMinimum({ part }: { part: PartDetails }) {
  const { t } = useTranslation();
  const stock = usePartStock(part.id);
  const preferences = usePreferences();
  if (part.not_stocked) return null;

  const minimum = part.minimum_stock_resolved;
  const basis = preferences.data?.stock_basis ?? "free";
  const have = stock.data ? (basis === "free" ? stock.data.available : stock.data.total) : null;

  return (
    <>
      <dt className="text-sm text-muted">{t("catalog.part.minimum.label")}</dt>
      <dd className="min-w-0 wrap-anywhere">
        {minimum === null ? (
          <span className="text-muted">{t("catalog.part.minimum.none")}</span>
        ) : (
          <>
            <span className="tabular-nums">{minimum}</span>
            {part.minimum_stock_from && (
              <span className="text-sm text-muted">
                {" "}
                {t("catalog.part.minimum.from", { category: part.minimum_stock_from.name })}
              </span>
            )}
          </>
        )}
        {minimum !== null && have !== null && have < minimum && (
          <span className="block text-sm font-semibold text-warn">
            {t(`catalog.part.minimum.below.${basis}`, { have, missing: minimum - have })}{" "}
            <Link to="/reorder" className="font-semibold text-primary hover:underline">
              {t("reorder.open")}
            </Link>
          </span>
        )}
      </dd>
    </>
  );
}
