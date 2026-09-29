import type { Net } from "@wiredex/api-client";
import { netCell } from "./netCells";
import { PinChip } from "./PinChip";
import { WireSwatch } from "./WireSwatch";

/** A net as its row reads: colour, name, its pins as chips, and notes (requirement 10.1). */
export function NetRow({ net, children }: { net: Net; children?: React.ReactNode }) {
  return (
    <tr className="border-b border-border">
      <td className={netCell}>
        <WireSwatch color={net.color} />
      </td>
      <th scope="row" className={`${netCell} font-semibold`}>
        {net.name}
      </th>
      <td className={netCell}>
        <ul className="flex flex-wrap gap-1">
          {net.pins.map((pin) => (
            <PinChip key={pin.ref} pin={pin} />
          ))}
        </ul>
      </td>
      <td className={`${netCell} text-muted`}>{net.notes}</td>
      {children}
    </tr>
  );
}
