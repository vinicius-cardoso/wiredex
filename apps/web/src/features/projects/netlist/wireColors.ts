import type { WireColor } from "@wiredex/api-client";

/** The ten, in the resistor code's order (spec 11, decision 7). */
export const WIRE_COLORS: readonly WireColor[] = [
  "black",
  "brown",
  "red",
  "orange",
  "yellow",
  "green",
  "blue",
  "violet",
  "grey",
  "white",
];

/**
 * Each colour's swatch class, spelled out whole so Tailwind finds it. The tokens are the same
 * in both themes (decision 15); black and white carry a strong border to show on either
 * background, the others a faint one.
 */
export const SWATCH: Record<WireColor, string> = {
  black: "bg-wire-black border-border-strong",
  brown: "bg-wire-brown border-border",
  red: "bg-wire-red border-border",
  orange: "bg-wire-orange border-border",
  yellow: "bg-wire-yellow border-border",
  green: "bg-wire-green border-border",
  blue: "bg-wire-blue border-border",
  violet: "bg-wire-violet border-border",
  grey: "bg-wire-grey border-border",
  white: "bg-wire-white border-border-strong",
};

/** A colour's name as an i18n key, typed so a new colour can't ship untranslated. */
export function colorKey(color: WireColor | null) {
  return `projects.netlist.colors.${color ?? "none"}` as const;
}
