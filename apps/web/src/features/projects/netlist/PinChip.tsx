import type { NetPin, Resolution } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";

/**
 * One reference as a chip: its canonical text and, when resolved, its pin's label, `U1.25
 * GPIO21`. An unchecked or unresolved reference says which in words beside an icon, never by
 * colour alone (requirement 10.2), and 12's findings will mark the same chip.
 */
export function PinChip({ pin }: { pin: NetPin }) {
  const { t } = useTranslation();
  const resolution = pin.resolution;
  const flagged = resolution !== "resolved";
  const unresolved = flagged && resolution !== "unchecked";
  const tone = unresolved ? "border-crit text-crit" : flagged ? "border-warn" : "border-border";
  return (
    <li
      className={`inline-flex max-w-full flex-wrap items-baseline gap-x-1 rounded border px-2 py-0.5 ${tone}`}
    >
      <span className="font-mono">{pin.ref}</span>
      {pin.label && <span className="text-muted">{pin.label}</span>}
      {resolution !== "resolved" && (
        <span className="text-xs">
          <span aria-hidden="true">{unresolved ? "⚠ " : "? "}</span>
          {t(resolutionKey(resolution))}
        </span>
      )}
    </li>
  );
}

/** What an unchecked or unresolved reference says, as a typed i18n key. */
function resolutionKey(resolution: Exclude<Resolution, "resolved">) {
  return `projects.netlist.resolution.${resolution}` as const;
}
