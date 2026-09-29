import { screen, within } from "@testing-library/react";
import type { Finding } from "@wiredex/api-client";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "../../../test/render";
import { FindingsList } from "./FindingsList";

const SDA = "0199aaaa-0000-7000-8000-0000000000e1";
const SDA2 = "0199aaaa-0000-7000-8000-0000000000e2";

function aFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    code: "pin_reused",
    severity: "error",
    message: "U1.25 is in the nets SDA, SDA2",
    net_ids: [SDA, SDA2],
    nets: ["SDA", "SDA2"],
    refs: ["U1.25"],
    part_id: null,
    part_name: null,
    designators: null,
    levels: [],
    ...overrides,
  };
}

const noPinout = aFinding({
  code: "no_pinout",
  severity: "warning",
  net_ids: [SDA],
  nets: ["SDA"],
  refs: ["R1.2"],
  part_id: "0199aaaa-0000-7000-8000-0000000000f1",
  part_name: "Resistor 4k7 0805",
  designators: "R1, R2",
});

describe("FindingsList", () => {
  it("lists errors before warnings, each with its severity in words", () => {
    renderWithProviders(<FindingsList findings={[noPinout, aFinding()]} />);

    const items = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Error");
    expect(items[0]).toHaveTextContent("U1.25 is in more than one net.");
    expect(items[1]).toHaveTextContent("Warning");
    expect(items[1]).toHaveTextContent(
      "Resistor 4k7 0805 has no pinout, so the pins of R1, R2 aren't checked.",
    );
  });

  it("links each finding to the net rows it names", () => {
    renderWithProviders(<FindingsList findings={[aFinding()]} />);

    expect(screen.getByRole("link", { name: "SDA" })).toHaveAttribute("href", `#net-${SDA}`);
    expect(screen.getByRole("link", { name: "SDA2" })).toHaveAttribute("href", `#net-${SDA2}`);
  });

  it("names the levels a voltage mismatch joins", () => {
    renderWithProviders(
      <FindingsList
        findings={[
          aFinding({
            code: "voltage_mismatch",
            refs: ["U1.1", "U1.19"],
            net_ids: [SDA],
            nets: ["VCC"],
            levels: [
              { voltage: "3.3", refs: ["U1.1"] },
              { voltage: "5", refs: ["U1.19"] },
            ],
          }),
        ]}
      />,
    );

    expect(screen.getByText("A net joins 3.3 V and 5 V pins.")).toBeInTheDocument();
  });

  it("says so when the wiring has nothing to report", () => {
    renderWithProviders(<FindingsList findings={[]} />);

    expect(screen.getByText("No problems found in the wiring.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });
});
