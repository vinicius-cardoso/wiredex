import type { StockStatus } from "@wiredex/api-client";

/** Each stock status's i18n key, so the lines and the report name a status the same way. */
export function stockStatusKey(status: StockStatus) {
  return `projects.bom.status.${status}` as const;
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
