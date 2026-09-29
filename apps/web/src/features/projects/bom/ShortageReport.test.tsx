import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderInRouter } from "../../../test/render";
import { aBom, aBomLine, aBomPart, aBomPartFacts } from "../../../test/server";
import { ShortageReport } from "./ShortageReport";

const SENSOR_ID = "0199cccc-0000-7000-8000-0000000000d2";
const GONE_ID = "0199cccc-0000-7000-8000-0000000000d9";

const resistor = aBomPart({ available: 3, short: 1, status: "short" });
const sensor = aBomPart({
  part_id: SENSOR_ID,
  need: 2,
  available: 0,
  short: 2,
  status: "short",
  part: aBomPartFacts({ name: "BME280" }),
});
const gone = aBomPart({
  part_id: GONE_ID,
  need: 1,
  available: null,
  status: "unknown_part",
  part: null,
});
const wire = aBomPart({
  part_id: "0199cccc-0000-7000-8000-0000000000d3",
  need: 1,
  available: null,
  status: "not_stocked",
  part: aBomPartFacts({ name: "Hook-up wire 22 AWG", not_stocked: true }),
});

async function renderReport(parts = [resistor, sensor, gone, wire]) {
  const { report } = aBom({ lines: [aBomLine()], parts });
  renderInRouter(<ShortageReport report={report} />);
  return screen.findByRole("region", { name: "Shortages" });
}

function cellsOf(row: HTMLElement) {
  return [within(row).getByRole("rowheader"), ...within(row).getAllByRole("cell")].map(
    (cell) => cell.textContent,
  );
}

describe("ShortageReport", () => {
  it("counts the lines, the parts, what is short, the consumables and the unknown parts", async () => {
    const report = await renderReport();

    const counts = within(report)
      .getAllByRole("term")
      .map((term) => `${term.textContent} ${term.nextElementSibling?.textContent}`);
    expect(counts).toEqual([
      "Lines 1",
      "Parts 4",
      "Parts short 2",
      "Pieces short 3",
      "Not stocked 1",
      "Unknown parts 1",
    ]);
  });

  it("lists each short and unknown part with its numbers, linking to its page", async () => {
    const report = await renderReport();
    const table = within(report).getByRole("table", { name: "Parts short or unknown" });
    const [, ...rows] = within(table).getAllByRole("row");

    expect(rows.map(cellsOf)).toEqual([
      ["4.7 kΩ 1% 0805", "4", "3", "1"],
      ["BME280", "2", "0", "2"],
      ["Unknown part", "1", "—", "—"],
    ]);
    expect(within(table).getByRole("link", { name: "BME280" })).toHaveAttribute(
      "href",
      `/parts/${SENSOR_ID}`,
    );
    expect(within(table).getByRole("link", { name: "Unknown part" })).toHaveAttribute(
      "href",
      `/parts/${GONE_ID}`,
    );
    // A consumable is never short, so it isn't listed as missing.
    expect(within(table).queryByText("Hook-up wire 22 AWG")).not.toBeInTheDocument();
  });

  it("says nothing is short once the BOM is complete", async () => {
    const report = await renderReport([aBomPart(), wire]);

    expect(within(report).getByText("Nothing is short.")).toBeInTheDocument();
    expect(within(report).queryByRole("table")).not.toBeInTheDocument();
  });
});
