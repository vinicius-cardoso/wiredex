import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createTestQueryClient, renderInRouter } from "../../../test/render";
import { aBomPartFacts, aHeldPart, aLifecycle, respondWithLifecycle } from "../../../test/server";
import { HoldingsSection } from "./HoldingsSection";

const REVISION_ID = "0199eeee-0000-7000-8000-00000000000a";
const esp32 = "0199cccc-0000-7000-8000-0000000000e1";
const resistor = "0199cccc-0000-7000-8000-0000000000e2";

function render(status: "draft" | "reserved" | "built" | "dismantled", lifecycle = aLifecycle()) {
  respondWithLifecycle(REVISION_ID, lifecycle);
  renderInRouter(<HoldingsSection revisionId={REVISION_ID} status={status} />, {
    queryClient: createTestQueryClient(),
  });
}

describe("HoldingsSection", () => {
  it("shows nothing while the revision is a draft", () => {
    render("draft");
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });

  it("shows nothing while the revision is dismantled", () => {
    render("dismantled");
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });

  it("shows each reserved part with its quantity, its locations and its units", async () => {
    render(
      "reserved",
      aLifecycle({
        status: "reserved",
        transitions: ["build", "cancel"],
        deletable: false,
        parts: [
          aHeldPart({
            part_id: esp32,
            part: aBomPartFacts({ name: "ESP32-WROOM", tracked_individually: true }),
            reserved: [
              {
                location_id: "0199aaaa-0000-7000-8000-000000000001",
                location_code: "WX-L-0001",
                quantity: 1,
              },
            ],
            consumed: 0,
            units: [
              {
                unit_id: "0199dddd-0000-7000-8000-000000000101",
                code: "WX-U-0001",
                location_code: "WX-L-0001",
              },
            ],
          }),
          aHeldPart({
            part_id: resistor,
            part: aBomPartFacts({ name: "10k 0805" }),
            reserved: [
              {
                location_id: "0199aaaa-0000-7000-8000-000000000003",
                location_code: "WX-L-0003",
                quantity: 3,
              },
            ],
            consumed: 0,
            units: [],
          }),
        ],
      }),
    );

    await screen.findByRole("link", { name: "ESP32-WROOM" });
    const section = screen.getByRole("region", { name: "What this reserves" });
    expect(section).toHaveTextContent("1 set aside");
    expect(section).toHaveTextContent("1 in WX-L-0001");
    expect(section).toHaveTextContent("3 in WX-L-0003");

    const unit = within(section).getByRole("link", { name: "WX-U-0001" });
    expect(unit).toHaveAttribute("href", "/units/0199dddd-0000-7000-8000-000000000101");
  });

  it("shows each built part with the quantity that went into the build", async () => {
    render(
      "built",
      aLifecycle({
        status: "built",
        transitions: ["dismantle"],
        deletable: false,
        parts: [
          aHeldPart({
            part_id: resistor,
            part: aBomPartFacts({ name: "10k 0805" }),
            reserved: [],
            consumed: 3,
            units: [],
          }),
        ],
      }),
    );

    await screen.findByRole("link", { name: "10k 0805" });
    const section = screen.getByRole("region", { name: "What went into this build" });
    expect(section).toHaveTextContent("3 in the build");
    // A built revision shows no location: its parts are on the board, not in a drawer.
    expect(section).not.toHaveTextContent("WX-L-");
  });
});
