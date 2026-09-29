import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderInRouter } from "../../../test/render";
import { aNet, aNetlist, aNetPin, aRevision, respondWithNetlist } from "../../../test/server";
import { NetlistSection } from "./NetlistSection";

const REVISION = aRevision();

const sda = aNet({
  pins: [
    aNetPin({ ref: "R1.2", designator: "R1", pin: "2", resolution: "unchecked", label: null }),
    aNetPin(),
    aNetPin({
      ref: "U2.3",
      designator: "U2",
      pin: "3",
      resolution: "unknown_designator",
      part_id: null,
      part_name: null,
      label: null,
      type: null,
      voltage: null,
    }),
  ],
});
const gnd = aNet({
  id: "0199aaaa-0000-7000-8000-0000000000e2",
  name: "GND",
  color: null,
  notes: "star point",
  pins: [aNetPin({ ref: "U1.14", pin: "14", label: "GND", type: "ground", voltage: null })],
});

async function renderSection(status: "draft" | "reserved" = "draft") {
  respondWithNetlist(REVISION.id, aNetlist({ nets: [sda, gnd], editable: status === "draft" }));
  renderInRouter(<NetlistSection revision={aRevision({ status })} />);
  const section = await screen.findByRole("region", { name: "Wiring" });
  await within(section).findByRole("table", { name: "Nets of the revision" });
  return section;
}

describe("NetlistSection", () => {
  it("shows each net with its color, name, pins and notes", async () => {
    const section = await renderSection();

    const row = within(section).getByRole("row", { name: /SDA/ });
    expect(within(row).getByText("Blue")).toBeInTheDocument();
    expect(within(row).getByText("U1.25")).toBeInTheDocument();
    expect(within(row).getByText("GPIO21")).toBeInTheDocument();
    const other = within(section).getByRole("row", { name: /GND/ });
    expect(within(other).getByText("No color")).toBeInTheDocument();
    expect(within(other).getByText("star point")).toBeInTheDocument();
  });

  it("says in words which references aren't checked or found", async () => {
    const section = await renderSection();

    expect(within(section).getByText("not checked: the part has no pinout")).toBeInTheDocument();
    expect(within(section).getByText("not on the BOM")).toBeInTheDocument();
    expect(
      within(section).getByText("2 nets connecting 4 pins.", { exact: false }),
    ).toBeInTheDocument();
    expect(
      within(section).getByText("1 not checked, 1 not found.", { exact: false }),
    ).toBeInTheDocument();
  });

  it("says why a revision that isn't a draft can't change", async () => {
    const section = await renderSection("reserved");

    expect(within(section).getByText(/only a draft's wiring can change/i)).toBeInTheDocument();
  });

  it("says when a locked revision has no nets", async () => {
    respondWithNetlist(REVISION.id, aNetlist({ nets: [], editable: false }));
    renderInRouter(<NetlistSection revision={aRevision({ status: "built" })} />);

    expect(await screen.findByText("No nets yet.")).toBeInTheDocument();
  });
});
