import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "../../../test/render";
import { aNet, aNetPin } from "../../../test/server";
import { WiringDiagram } from "./WiringDiagram";

const sensor = aNetPin({
  ref: "U2.3",
  designator: "U2",
  pin: "3",
  label: "SDA",
  part_name: "BME280",
});
const sda = aNet({ pins: [aNetPin(), sensor] });

describe("WiringDiagram", () => {
  it("draws the parts, their wired pins and a wire for the net, as one named image", () => {
    renderWithProviders(<WiringDiagram nets={[sda]} />);
    const drawing = screen.getByRole("img", { name: "Wiring diagram: 1 nets between 2 parts" });
    for (const text of ["U1", "ESP32-DevKitC", "25 GPIO21", "U2", "BME280", "3 SDA", "SDA"])
      expect(within(drawing).getAllByText(text).length).toBeGreaterThan(0);
    expect(within(drawing).getByText("SDA (Blue): U1.25 to U2.3")).toBeInTheDocument();
    const wire = drawing.querySelector("path.stroke-wire-blue");
    expect(wire).toHaveAttribute("d", expect.stringMatching(/^M /));
    expect(
      screen.getByText(/^Drawn from the nets below\. Point at a part, a pin or a wire/),
    ).toBeVisible();
  });

  it("draws an uncoloured net's wire muted, and names it so", () => {
    renderWithProviders(<WiringDiagram nets={[{ ...sda, color: null }]} />);
    expect(screen.getByText("SDA (No color): U1.25 to U2.3")).toBeInTheDocument();
    expect(screen.getByRole("img").querySelector("path.stroke-muted")).not.toBeNull();
  });

  it("marks a pin its part doesn't have", () => {
    const stray = { ...sensor, resolution: "unknown_pin" as const, label: null };
    renderWithProviders(<WiringDiagram nets={[aNet({ pins: [aNetPin(), stray] })]} />);
    expect(within(screen.getByRole("img")).getByText("3")).toHaveClass("fill-warn");
  });

  it("draws nothing until two pins are wired together", () => {
    const { container } = renderWithProviders(<WiringDiagram nets={[aNet()]} />);
    expect(container.querySelector("svg")).toBeNull();
  });

  it("speaks Brazilian Portuguese", () => {
    renderWithProviders(<WiringDiagram nets={[sda]} />, { language: "pt-BR" });
    expect(screen.getByRole("img", { name: /^Diagrama de ligações: 1 / })).toBeInTheDocument();
  });
});
