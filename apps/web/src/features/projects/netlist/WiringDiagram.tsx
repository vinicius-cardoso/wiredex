import type { Net, WireColor } from "@wiredex/api-client";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { DIAGRAM, layoutDiagram } from "./diagram";
import { colorKey } from "./wireColors";
import { sameFocus, useWiring, type WiringFocus } from "./wiringFocus";

/** Each wire colour's stroke, spelled out whole so Tailwind finds it. */
const STROKE: Record<WireColor, string> = {
  black: "stroke-wire-black",
  brown: "stroke-wire-brown",
  red: "stroke-wire-red",
  orange: "stroke-wire-orange",
  yellow: "stroke-wire-yellow",
  green: "stroke-wire-green",
  blue: "stroke-wire-blue",
  violet: "stroke-wire-violet",
  grey: "stroke-wire-grey",
  white: "stroke-wire-white",
};

/**
 * A revision's wiring drawn from its nets: each part a box with the pins it has wired, each net
 * a wire in its colour, named beside the pin it leaves from. Pointing at a part, a pin or a wire
 * lights the nets on it and dims the others; a click keeps them lit, and on a wire also shows
 * its row in the table. It is one image to a screen reader, which that table spells out. The drawing keeps its natural size and
 * scrolls inside its own frame when the block is narrower, never the page.
 */
export function WiringDiagram({ nets }: { nets: readonly Net[] }) {
  const { t } = useTranslation();
  const { lit, held, hover, hold } = useWiring();
  const diagram = useMemo(() => layoutDiagram(nets), [nets]);
  if (diagram.wires.length === 0) return null;
  const netOf = new Map(nets.map((net) => [net.name, net.id]));
  const netsAt = new Map<string, string[]>();
  for (const net of nets)
    for (const pin of net.pins)
      for (const key of [pin.ref, pin.designator])
        netsAt.set(key, [...(netsAt.get(key) ?? []), net.id]);
  /** Dimmed when something is lit and none of IDS is. */
  const dim = (ids: readonly string[]) =>
    lit && !ids.some((id) => lit.has(id)) ? "opacity-20" : "";
  /** Pointing lights FOCUS; a click holds it, and a second click lets it go. */
  const pointing = (focus: WiringFocus, then?: () => void) => ({
    onMouseEnter: () => hover(focus),
    onMouseLeave: () => hover(null),
    onClick: (event: { stopPropagation: () => void }) => {
      event.stopPropagation();
      const letGo = sameFocus(held, focus);
      hold(letGo ? null : focus);
      if (!letGo) then?.();
    },
  });

  return (
    <figure className="grid min-w-0 gap-1">
      <div className="overflow-x-auto rounded-lg border border-border bg-bg">
        {/* biome-ignore lint/a11y/useKeyWithClickEvents: the pointer's shortcut to what the net toggles and the table offer the keyboard */}
        <svg
          onClick={() => hold(null)}
          role="img"
          aria-label={t("projects.netlist.diagram.label", {
            nets: nets.length,
            parts: diagram.parts.length,
          })}
          viewBox={`0 0 ${diagram.width} ${diagram.height}`}
          width={diagram.width}
          height={diagram.height}
          className="mx-auto block font-mono text-[11px]"
        >
          {diagram.parts.map((part) => (
            <g
              key={part.designator}
              className={`cursor-pointer transition-opacity ${dim(netsAt.get(part.designator) ?? [])}`}
            >
              <rect
                {...pointing({ kind: "part", designator: part.designator })}
                x={part.x}
                y={part.y}
                width={part.width}
                height={part.height}
                rx={6}
                className="fill-surface stroke-border-strong"
              />
              <text
                x={part.x + 10}
                y={part.y + 19}
                className="pointer-events-none fill-text text-[13px] font-semibold"
              >
                {part.designator}
              </text>
              {part.name && (
                <text
                  x={part.x + 10}
                  y={part.y + 35}
                  className="pointer-events-none fill-muted font-sans"
                >
                  {clipped(part.name, 30)}
                </text>
              )}
              {part.pins.map((pin) => (
                <g key={pin.ref} {...pointing({ kind: "pin", ref: pin.ref })}>
                  {/* A wider target than the dot and its text. */}
                  <rect
                    x={part.side === "left" ? pin.x - part.width / 2 : pin.x - 8}
                    y={pin.y - DIAGRAM.row / 2}
                    width={part.width / 2 + 8}
                    height={DIAGRAM.row}
                    fill="transparent"
                  />
                  <circle cx={pin.x} cy={pin.y} r={3} className="fill-text" />
                  <text
                    x={part.side === "left" ? pin.x - 10 : pin.x + 10}
                    y={pin.y + 4}
                    textAnchor={part.side === "left" ? "end" : "start"}
                    className={pin.known ? "fill-text" : "fill-warn"}
                  >
                    {clipped(pin.label ? `${pin.pin} ${pin.label}` : pin.pin, 26)}
                  </text>
                </g>
              ))}
            </g>
          ))}
          {diagram.wires.map((wire) => (
            <g
              key={wire.key}
              fill="none"
              strokeLinecap="round"
              className={`cursor-pointer transition-opacity ${dim([netOf.get(wire.net) ?? ""])}`}
              {...pointing({ kind: "net", id: netOf.get(wire.net) ?? "" }, () =>
                showRow(netOf.get(wire.net) ?? ""),
              )}
            >
              {/* A line under the wire keeps a black or a white one in sight in either theme. */}
              <path d={wire.path} strokeWidth={4.5} className="stroke-border-strong" />
              <path
                d={wire.path}
                strokeWidth={lit?.has(netOf.get(wire.net) ?? "") ? 4 : 2.5}
                className={wire.color ? STROKE[wire.color] : "stroke-muted"}
              >
                <title>
                  {t("projects.netlist.diagram.wire", {
                    net: wire.net,
                    color: t(colorKey(wire.color)),
                    from: wire.from,
                    to: wire.to,
                  })}
                </title>
              </path>
              {/* A wide, unseen stroke, so a thin wire is easy to point at. */}
              <path d={wire.path} strokeWidth={14} stroke="transparent" />
            </g>
          ))}
          {diagram.labels.map((label) => (
            <text
              key={label.key}
              x={label.x}
              y={label.y}
              textAnchor={label.anchor}
              // Outlined in the background's colour, so a name reads over the wires it crosses.
              paintOrder="stroke"
              strokeWidth={3}
              className={`pointer-events-none fill-text stroke-bg text-[10px] transition-opacity ${dim([label.key])}`}
            >
              {clipped(label.net, DIAGRAM.channel / 12)}
            </text>
          ))}
        </svg>
      </div>
      <figcaption className="text-xs text-muted">
        {t("projects.netlist.diagram.caption")}
      </figcaption>
    </figure>
  );
}

/** Brings a net's row of the table into view; the row marks itself while its net is lit. */
function showRow(netId: string) {
  const row = document.getElementById(`net-${netId}`);
  // jsdom has no layout, and so no scrolling.
  row?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
}

/** TEXT cut to LENGTH characters with an ellipsis, so it stays inside its box. */
function clipped(text: string, length: number): string {
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}
