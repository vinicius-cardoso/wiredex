import type { Net, Severity } from "@wiredex/api-client";
import { netCell } from "./netCells";
import { PinChip } from "./PinChip";
import { WireSwatch } from "./WireSwatch";

type Props = {
  net: Net;
  /** The worst finding's severity per reference, for its chip (spec 12, requirement 10.2). */
  severities?: ReadonlyMap<string, Severity> | undefined;
  children?: React.ReactNode;
};

/**
 * A net as its row reads: colour, name, its pins as chips, and notes (requirement 10.1). Its
 * `net-<id>` anchor is where a finding naming it links (spec 12, requirement 10.1).
 */
export function NetRow({ net, severities, children }: Props) {
  return (
    <tr id={`net-${net.id}`} className="border-b border-border">
      <th scope="row" className={`${netCell} font-semibold`}>
        {net.name}
      </th>
      <td className={netCell}>
        <WireSwatch color={net.color} />
      </td>
      <td className={netCell}>
        <ul className="flex flex-wrap gap-1">
          {net.pins.map((pin) => (
            <PinChip key={pin.ref} pin={pin} severity={severities?.get(pin.ref)} />
          ))}
        </ul>
      </td>
      <td className={`${netCell} text-muted`}>{net.notes}</td>
      {children}
    </tr>
  );
}
