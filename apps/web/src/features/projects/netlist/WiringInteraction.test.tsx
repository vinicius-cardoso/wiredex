import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderInRouter } from "../../../test/render";
import { aNet, aNetlist, aNetPin, aRevision, respondWithNetlist } from "../../../test/server";
import { NetlistSection } from "./NetlistSection";

const REVISION = aRevision();
const pin = (ref: string, type: "io" | "power" | "ground" = "io") => {
  const [designator = "", number = ""] = ref.split(".");
  return aNetPin({ ref, designator, pin: number, label: null, type });
};
const SDA = aNet({ id: "net-sda", name: "SDA", color: "blue", pins: [pin("U1.21"), pin("U2.3")] });
const KEY = aNet({ id: "net-key", name: "KEY", color: "white", pins: [pin("U1.5"), pin("SW1.1")] });
const GND = aNet({
  id: "net-gnd",
  name: "GND",
  color: "black",
  pins: [pin("U1.7", "ground"), pin("U2.1", "ground"), pin("SW1.2")],
});

async function renderWiring() {
  respondWithNetlist(REVISION.id, aNetlist({ nets: [SDA, KEY, GND] }));
  const { router } = renderInRouter(<NetlistSection revision={REVISION} />);
  const section = await screen.findByRole("region", { name: "Wiring" });
  const drawing = await within(section).findByRole("img", { name: /^Wiring diagram/ });
  return { section, drawing, router, user: userEvent.setup() };
}

/** The wires of the drawing by net, each the group that dims and lights as one. */
function wires(drawing: HTMLElement): Record<string, Element[]> {
  const byNet: Record<string, Element[]> = {};
  for (const title of drawing.querySelectorAll("title")) {
    const net = (title.textContent ?? "").split(" ")[0] ?? "";
    const group = title.closest("g");
    if (group) byNet[net] = [...(byNet[net] ?? []), group];
  }
  return byNet;
}
const dimmed = (elements: Element[] = []) =>
  elements.every((el) => el.classList.contains("opacity-20"));
const toggle = (name: string) => screen.getByRole("button", { name });

describe("the wiring's diagram, toggles and table together", () => {
  it("lights a part's nets while it is pointed at, and dims the others", async () => {
    const { drawing, user } = await renderWiring();
    expect(dimmed(wires(drawing).SDA)).toBe(false);

    // SW1 is on KEY and GND, not on SDA.
    const part = within(drawing).getByText("SW1").closest("g")?.querySelector("rect") as Element;
    await user.hover(part);
    expect(dimmed(wires(drawing).SDA)).toBe(true);
    expect(dimmed(wires(drawing).KEY)).toBe(false);
    expect(dimmed(wires(drawing).GND)).toBe(false);
    await user.unhover(part);
    expect(dimmed(wires(drawing).SDA)).toBe(false);
  });

  it("lights the one net on a pin, and marks its row in the table", async () => {
    const { section, drawing, user } = await renderWiring();
    await user.hover(within(drawing).getByText("21"));
    expect(dimmed(wires(drawing).SDA)).toBe(false);
    expect(dimmed(wires(drawing).KEY)).toBe(true);
    expect(dimmed(wires(drawing).GND)).toBe(true);
    expect(within(section).getByRole("row", { name: /SDA/ })).toHaveAttribute("data-lit", "true");
    expect(within(section).getByRole("row", { name: /KEY/ })).not.toHaveAttribute("data-lit");
  });

  it("keeps a clicked wire lit until it is clicked again or the drawing is", async () => {
    const { section, drawing, user } = await renderWiring();
    const wire = wires(drawing).KEY?.[0] as Element;
    await user.click(wire);
    await user.unhover(wire);
    expect(dimmed(wires(drawing).SDA)).toBe(true);
    expect(within(section).getByRole("row", { name: /KEY/ })).toHaveAttribute("data-lit", "true");

    // Pointing elsewhere shows that instead, and leaving it brings the held net back.
    await user.hover(within(drawing).getByText("21"));
    expect(dimmed(wires(drawing).KEY)).toBe(true);
    await user.unhover(within(drawing).getByText("21"));
    expect(dimmed(wires(drawing).KEY)).toBe(false);

    await user.click(wire);
    await user.unhover(wire);
    expect(dimmed(wires(drawing).SDA)).toBe(false);

    await user.click(wire);
    await user.unhover(wire);
    await user.click(drawing);
    expect(dimmed(wires(drawing).SDA)).toBe(false);
  });

  it("lights a net's wire from its row and from its toggle", async () => {
    const { section, drawing, user } = await renderWiring();
    await user.hover(within(section).getByRole("row", { name: /GND/ }));
    expect(dimmed(wires(drawing).SDA)).toBe(true);
    expect(dimmed(wires(drawing).GND)).toBe(false);
    await user.unhover(within(section).getByRole("row", { name: /GND/ }));

    await user.hover(toggle("SDA"));
    expect(dimmed(wires(drawing).GND)).toBe(true);
    expect(dimmed(wires(drawing).SDA)).toBe(false);
  });

  it("draws only the nets left on, keeps them in the address, and all of them in the table", async () => {
    const { section, router, user } = await renderWiring();
    const filter = within(section).getByRole("group", { name: "Nets drawn in the diagram" });
    expect(within(filter).getByRole("button", { name: "GND" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(within(filter).getByRole("button", { name: "GND" }));
    await waitFor(() => expect(router.state.location.search).toEqual({ hide: ["GND"] }));
    expect(within(filter).getByRole("button", { name: "GND" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    const drawing = within(section).getByRole("img", {
      name: "Wiring diagram: 2 nets between 3 parts",
    });
    expect(wires(drawing).GND).toBeUndefined();
    expect(within(drawing).queryByText("7")).toBeNull();
    expect(within(section).getByRole("row", { name: /GND/ })).toBeVisible();

    await user.click(within(filter).getByRole("button", { name: "GND" }));
    await waitFor(() => expect(router.state.location.search).toEqual({}));
    expect(wires(within(section).getByRole("img")).GND).toHaveLength(2);
  });

  it("offers all, none, the power nets and the signals", async () => {
    const { section, router, user } = await renderWiring();
    const filter = within(section).getByRole("group", { name: "Nets drawn in the diagram" });

    await user.click(within(filter).getByRole("button", { name: "Signals" }));
    await waitFor(() => expect(router.state.location.search).toEqual({ hide: ["GND"] }));
    await user.click(within(filter).getByRole("button", { name: "Power" }));
    await waitFor(() => expect(router.state.location.search).toEqual({ hide: ["SDA", "KEY"] }));
    expect(within(section).getByRole("img", { name: /1 nets between 3 parts/ })).toBeVisible();

    await user.click(within(filter).getByRole("button", { name: "None" }));
    expect(
      await within(section).findByText("No net is shown. Turn one on to draw it."),
    ).toBeVisible();
    expect(within(section).queryByRole("img")).toBeNull();
    await user.click(within(filter).getByRole("button", { name: "All" }));
    await waitFor(() => expect(router.state.location.search).toEqual({}));
    expect(within(section).getByRole("img", { name: /3 nets between 3 parts/ })).toBeVisible();
  });

  it("opens with the nets the address hides left out, ignoring names it doesn't have", async () => {
    const { section, router } = await renderWiring();
    await act(() => router.navigate({ to: "/", search: { hide: ["SDA", "GONE"] } as never }));
    expect(
      await within(section).findByRole("img", { name: "Wiring diagram: 2 nets between 3 parts" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "SDA" })).toHaveAttribute("aria-pressed", "false");
  });

  it("offers no toggles while no net joins two pins", async () => {
    respondWithNetlist(REVISION.id, aNetlist({ nets: [aNet()] }));
    renderInRouter(<NetlistSection revision={REVISION} />);
    const section = await screen.findByRole("region", { name: "Wiring" });
    await within(section).findByRole("table");
    expect(within(section).queryByRole("group", { name: "Nets drawn in the diagram" })).toBeNull();
  });
});
