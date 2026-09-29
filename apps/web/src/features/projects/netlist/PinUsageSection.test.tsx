import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PinUsagePin, PinUse } from "@wiredex/api-client";
import { describe, expect, it, vi } from "vitest";
import { renderInRouter } from "../../../test/render";
import { aPinUsage, aPinUse, respondWithPinUsage } from "../../../test/server";
import { PinUsageSection } from "./PinUsageSection";

const BOARD = "0199aaaa-0000-7000-8000-00000000d001";

function aUsagePin(number: string, label: string, functions: string[], uses: PinUse[] = []) {
  const pin: PinUsagePin = { number, label, type: "io", functions, voltage: null, uses };
  return pin;
}

const gpio21 = aUsagePin(
  "25",
  "GPIO21",
  ["SDA"],
  [
    aPinUse(),
    aPinUse({
      revision_id: "0199aaaa-0000-7000-8000-00000000b002",
      revision_label: "B",
      status: "built",
      net_id: "0199aaaa-0000-7000-8000-00000000c002",
      color: "blue",
    }),
  ],
);
const gpio4 = aUsagePin("26", "GPIO4", ["ADC2_0"]);

function renderSection(usage = aPinUsage({ part_id: BOARD, pins: [gpio21, gpio4] })) {
  respondWithPinUsage(BOARD, usage);
  renderInRouter(<PinUsageSection partId={BOARD} />);
  return screen.findByRole("region", { name: "Pin usage" });
}

describe("PinUsageSection", () => {
  it("shows each pin with the nets on it, linking to their revisions", async () => {
    const section = await renderSection();

    const row = within(section).getByRole("row", { name: /^25/ });
    expect(row).toHaveTextContent("GPIO21");
    const links = within(row).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Weather station · A",
      "Weather station · B",
    ]);
    expect(links[1]).toHaveAttribute(
      "href",
      "/projects/0199aaaa-0000-7000-8000-00000000a001/revisions/0199aaaa-0000-7000-8000-00000000b002#net-0199aaaa-0000-7000-8000-00000000c002",
    );
    expect(row).toHaveTextContent("built");
    expect(within(section).getByRole("row", { name: /^26/ })).toHaveTextContent("Free");
  });

  it("lists the numbers the pinout lacks as other pins", async () => {
    const section = await renderSection(
      aPinUsage({
        part_id: BOARD,
        pins: [gpio4],
        others: [{ pin: "34", uses: [aPinUse({ net_name: "SOIL" })] }],
      }),
    );

    expect(within(section).getByRole("columnheader", { name: "Other pins" })).toBeInTheDocument();
    expect(within(section).getByRole("row", { name: /^34/ })).toHaveTextContent("SOIL");
  });

  it("keeps the pins whose number, label or function holds the filter", async () => {
    const section = await renderSection();
    const user = userEvent.setup();
    const filter = within(section).getByRole("searchbox", { name: "Filter pins" });

    await user.type(filter, "gpio4");
    expect(within(section).queryByRole("row", { name: /^25/ })).toBeNull();
    expect(within(section).getByRole("row", { name: /^26/ })).toBeInTheDocument();

    await user.clear(filter);
    await user.type(filter, "sda");
    expect(within(section).getByRole("row", { name: /^25/ })).toBeInTheDocument();
    expect(within(section).queryByRole("row", { name: /^26/ })).toBeNull();

    await user.type(filter, "x");
    expect(within(section).getByText("No pin matches that filter.")).toBeInTheDocument();
  });

  it("shows nothing for a part with no pinout that no net names", async () => {
    const reads = respondWithPinUsage(BOARD, aPinUsage({ part_id: BOARD }));
    renderInRouter(<PinUsageSection partId={BOARD} />);

    await vi.waitFor(() => expect(reads).toHaveLength(1));
    expect(screen.queryByRole("region", { name: "Pin usage" })).toBeNull();
  });
});
