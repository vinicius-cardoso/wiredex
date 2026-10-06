import type { Net } from "@wiredex/api-client";
import { createContext, useContext } from "react";

/** What the reader points at in the wiring: a net, a part with all its wires, or one pin. */
export type WiringFocus =
  | { kind: "net"; id: string }
  | { kind: "part"; designator: string }
  | { kind: "pin"; ref: string };

/** The ids of the nets FOCUS lights: the net itself, or every net on the part or the pin. */
export function netsLitBy(
  focus: WiringFocus | null,
  nets: readonly Net[],
): ReadonlySet<string> | null {
  if (!focus) return null;
  const lit = nets.filter((net) =>
    focus.kind === "net"
      ? net.id === focus.id
      : net.pins.some((pin) =>
          focus.kind === "part" ? pin.designator === focus.designator : pin.ref === focus.ref,
        ),
  );
  return new Set(lit.map((net) => net.id));
}

export function sameFocus(a: WiringFocus | null, b: WiringFocus | null): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** A net carries power when one of its pins is a supply or a ground pin. */
export function isPowerNet(net: Net): boolean {
  return net.pins.some((pin) => pin.type === "power" || pin.type === "ground");
}

type Wiring = {
  /** The nets lit by what is hovered, or else by what was clicked; null when nothing is. */
  lit: ReadonlySet<string> | null;
  /** What was clicked, which stays lit until it is clicked again. */
  held: WiringFocus | null;
  hover: (focus: WiringFocus | null) => void;
  hold: (focus: WiringFocus | null) => void;
};

/**
 * Shared by the diagram and the table of nets, so pointing at a net in either lights it in
 * both. Outside a wiring block nothing is lit and pointing does nothing.
 */
export const WiringContext = createContext<Wiring>({
  lit: null,
  held: null,
  hover: () => {},
  hold: () => {},
});

export function useWiring(): Wiring {
  return useContext(WiringContext);
}
