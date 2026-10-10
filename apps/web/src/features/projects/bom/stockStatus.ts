import type { BomPart, StockStatus } from "@wiredex/api-client";
import type { TFunction } from "i18next";

/** Each stock status's i18n key, so the lines and the report name a status the same way. */
export function stockStatusKey(status: StockStatus) {
  return `projects.bom.status.${status}` as const;
}

/**
 * A line's stock in words, with the numbers behind the verdict: *Enough in stock (20)* says how
 * many are available, and *Short (3 in stock, 8 needed)* how far off it is, across every line
 * of the part on this BOM. A consumable and an unknown part have no count to give.
 */
export function stockSentence(t: TFunction, part: BomPart): string {
  if (part.available === null) return t(stockStatusKey(part.status));
  if (part.status === "covered") {
    return t("projects.bom.status.coveredWith", { available: part.available });
  }
  if (part.status === "short") {
    return t("projects.bom.status.shortWith", { available: part.available, need: part.need });
  }
  return t(stockStatusKey(part.status));
}

/**
 * Each status's colour, from the theme tokens: covered reads as fine, short as the problem,
 * a consumable as quiet since it is never counted, and an unknown part as a warning to fix.
 */
export const stockStatusTone: Record<StockStatus, string> = {
  covered: "text-ok",
  short: "text-crit",
  not_stocked: "text-muted",
  unknown_part: "text-warn",
};
