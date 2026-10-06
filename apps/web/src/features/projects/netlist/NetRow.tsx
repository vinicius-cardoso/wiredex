import type { Net, Severity } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { netCell } from "./netCells";
import { PinChip } from "./PinChip";
import { WireSwatch } from "./WireSwatch";
import { useWiring } from "./wiringFocus";

type Props = {
  net: Net;
  /** The worst finding's severity per reference, for its chip (spec 12, requirement 10.2). */
  severities?: ReadonlyMap<string, Severity> | undefined;
  children?: React.ReactNode;
};

/**
 * A net as its row reads: colour, name, its pins as chips, and notes (requirement 10.1). Its
 * `net-<id>` anchor is where a finding naming it links (spec 12, requirement 10.1). Pointing at
 * the row lights the net's wire in the diagram, and the row is marked while its net is lit.
 */
export function NetRow({ net, severities, children }: Props) {
  const { t } = useTranslation();
  const { lit, hover } = useWiring();
  return (
    <tr
      id={`net-${net.id}`}
      data-lit={lit?.has(net.id) ? "true" : undefined}
      onMouseEnter={() => hover({ kind: "net", id: net.id })}
      onMouseLeave={() => hover(null)}
      className={`border-b border-border ${lit?.has(net.id) ? "bg-surface-2" : ""}`}
    >
      <th scope="row" className={`${netCell} font-semibold`}>
        {net.name}
      </th>
      <td data-label={t("projects.netlist.columns.color")} className={netCell}>
        <WireSwatch color={net.color} />
      </td>
      <td data-label={t("projects.netlist.columns.pins")} className={netCell}>
        <ul className="flex flex-wrap gap-1">
          {net.pins.map((pin) => (
            <PinChip key={pin.ref} pin={pin} severity={severities?.get(pin.ref)} />
          ))}
        </ul>
      </td>
      <td data-label={t("projects.netlist.columns.notes")} className={`${netCell} text-muted`}>
        {net.notes}
      </td>
      {children}
    </tr>
  );
}
