import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderInRouter } from "../../../test/render";
import {
  aBom,
  aBomLine,
  aBomPart,
  aBomPartFacts,
  aRevision,
  respondWithBom,
} from "../../../test/server";
import { BomSection } from "./BomSection";

const REVISION_ID = aRevision().id;
const SENSOR_ID = "0199cccc-0000-7000-8000-0000000000d2";
const WIRE_ID = "0199cccc-0000-7000-8000-0000000000d3";

const resistor = aBomPart({ available: 3, short: 1, status: "short" });
const sensor = aBomPart({
  part_id: SENSOR_ID,
  need: 1,
  available: 1,
  status: "covered",
  part: aBomPartFacts({ name: "BME280", manufacturer: "Bosch", mpn: "BME280" }),
});
const wire = aBomPart({
  part_id: WIRE_ID,
  need: 1,
  available: null,
  status: "not_stocked",
  part: aBomPartFacts({
    name: "Hook-up wire 22 AWG",
    manufacturer: null,
    mpn: null,
    not_stocked: true,
  }),
});

const lines = [
  aBomLine({ notes: "I²C pull-ups" }),
  aBomLine({
    id: "0199abab-0000-7000-8000-000000000002",
    part_id: SENSOR_ID,
    designators: ["U1"],
    designator_text: "U1",
    quantity: 1,
  }),
  aBomLine({
    id: "0199abab-0000-7000-8000-000000000003",
    part_id: WIRE_ID,
    designators: [],
    designator_text: "",
    quantity: 1,
    notes: "2 m",
  }),
];

async function renderSection(status: "draft" | "reserved" = "draft") {
  respondWithBom(
    aBom({ lines, parts: [resistor, sensor, wire] }, { status, editable: status === "draft" }),
  );
  renderInRouter(<BomSection revision={aRevision({ status })} />);
  const section = await screen.findByRole("region", { name: "Bill of materials" });
  await within(section).findByRole("table", { name: "Lines of the bill of materials" });
  return section;
}

function cellsOf(row: HTMLElement) {
  return within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
}

describe("BomSection", () => {
  it("lists every line with its designators, part, quantity, notes and stock status", async () => {
    const section = await renderSection();
    const table = within(section).getByRole("table", { name: "Lines of the bill of materials" });
    const [, ...rows] = within(table).getAllByRole("row");

    // A draft's rows end with their buttons, and the table with the row that adds a line.
    expect(rows.map((row) => cellsOf(row).slice(0, 5))).toEqual([
      ["R1–R4", "4.7 kΩ 1% 0805RC0805FR-074K7L", "4", "I²C pull-ups", "Short"],
      ["U1", "BME280BME280", "1", "—", "Enough in stock"],
      ["—", "Hook-up wire 22 AWG", "1", "2 m", "Not stocked"],
      expect.any(Array),
    ]);
    expect(rows.at(-1)).toHaveAccessibleName("New line");
    expect(within(table).getByRole("link", { name: "BME280" })).toHaveAttribute(
      "href",
      `/parts/${SENSOR_ID}`,
    );
    expect(within(section).getByRole("region", { name: "Shortages" })).toBeInTheDocument();
  });

  it("shows a reserved revision's lines without controls, and says why", async () => {
    const section = await renderSection("reserved");

    expect(
      within(section).getByText(
        "Only a draft's bill of materials can change; this revision is reserved.",
      ),
    ).toBeInTheDocument();
    expect(within(section).getAllByRole("row")).not.toHaveLength(0);
    expect(within(section).queryByRole("button")).not.toBeInTheDocument();
    expect(within(section).queryByRole("textbox")).not.toBeInTheDocument();
    // A revision that isn't a draft titles its report as what building it again would miss.
    expect(
      within(section).getByRole("region", { name: "What building it again would be missing" }),
    ).toBeInTheDocument();
  });

  it("says a locked BOM with no lines has none, in Portuguese too", async () => {
    respondWithBom(aBom({ lines: [], parts: [] }, { status: "built", editable: false }));
    renderInRouter(<BomSection revision={aRevision({ status: "built" })} />, {
      language: "pt-BR",
    });

    const section = await screen.findByRole("region", { name: "Lista de materiais" });
    expect(await within(section).findByText("Nenhuma linha ainda.")).toBeInTheDocument();
    expect(
      within(section).getByText(
        "Só a lista de materiais de um rascunho pode mudar; esta revisão está montada.",
      ),
    ).toBeInTheDocument();
    expect(within(section).queryByRole("table")).not.toBeInTheDocument();
  });

  it("offers a draft with no lines the row that adds one, and no report yet", async () => {
    respondWithBom(aBom({ lines: [], parts: [] }));
    renderInRouter(<BomSection revision={aRevision()} />);

    const section = await screen.findByRole("region", { name: "Bill of materials" });
    expect(await within(section).findByRole("row", { name: "New line" })).toBeInTheDocument();
    expect(within(section).queryByRole("region", { name: "Shortages" })).not.toBeInTheDocument();
  });

  it("says when the BOM can't be loaded", async () => {
    respondWithBom(aBom({}, { revision_id: "0199eeee-0000-7000-8000-0000000000ff" }));
    renderInRouter(<BomSection revision={aRevision({ id: REVISION_ID })} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The bill of materials couldn't be loaded.",
    );
  });
});
