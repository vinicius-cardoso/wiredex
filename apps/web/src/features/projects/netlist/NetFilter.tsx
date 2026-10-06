import type { Net } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { SWATCH } from "./wireColors";
import { isPowerNet, useWiring } from "./wiringFocus";

type Props = {
  nets: readonly Net[];
  /** The names of the nets left out of the diagram. */
  hidden: ReadonlySet<string>;
  onChange: (hidden: string[]) => void;
};

const chip =
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs transition-colors";
const preset = "rounded-md border border-border-strong px-2 py-0.5 text-xs hover:bg-surface-2";

/**
 * Which nets the diagram draws, and its legend: a toggle for each net, its colour beside its
 * name, and shortcuts for all, none, the power nets and the signals. Pointing at a net's toggle
 * lights its wire, as pointing at the wire does.
 */
export function NetFilter({ nets, hidden, onChange }: Props) {
  const { t } = useTranslation();
  const { lit, hover } = useWiring();
  const names = nets.map((net) => net.name);
  const power = nets.filter(isPowerNet).map((net) => net.name);
  const signals = names.filter((name) => !power.includes(name));

  function toggle(name: string) {
    onChange(hidden.has(name) ? [...hidden].filter((each) => each !== name) : [...hidden, name]);
  }

  return (
    <fieldset className="grid min-w-0 gap-2">
      <legend className="sr-only">{t("projects.netlist.filter.legend")}</legend>
      <div className="flex flex-wrap items-center gap-2">
        <span aria-hidden="true" className="text-xs text-muted">
          {t("projects.netlist.filter.show")}
        </span>
        <button type="button" className={preset} onClick={() => onChange([])}>
          {t("projects.netlist.filter.all")}
        </button>
        <button type="button" className={preset} onClick={() => onChange(names)}>
          {t("projects.netlist.filter.none")}
        </button>
        {/* The two halves only help when the netlist has both. */}
        {power.length > 0 && signals.length > 0 && (
          <>
            <button type="button" className={preset} onClick={() => onChange(signals)}>
              {t("projects.netlist.filter.power")}
            </button>
            <button type="button" className={preset} onClick={() => onChange(power)}>
              {t("projects.netlist.filter.signals")}
            </button>
          </>
        )}
      </div>
      <ul className="flex flex-wrap gap-1.5">
        {nets.map((net) => {
          const shown = !hidden.has(net.name);
          return (
            <li key={net.id}>
              <button
                type="button"
                aria-pressed={shown}
                onClick={() => toggle(net.name)}
                onMouseEnter={() => hover({ kind: "net", id: net.id })}
                onMouseLeave={() => hover(null)}
                onFocus={() => hover({ kind: "net", id: net.id })}
                onBlur={() => hover(null)}
                className={`${chip} ${
                  shown
                    ? "border-border-strong bg-surface-2"
                    : "border-border text-muted line-through"
                } ${lit?.has(net.id) ? "ring-2 ring-primary" : ""}`}
              >
                <span
                  aria-hidden="true"
                  className={`inline-block size-2.5 rounded-full border ${
                    net.color ? SWATCH[net.color] : "border-border-strong"
                  }`}
                />
                {net.name}
              </button>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}
