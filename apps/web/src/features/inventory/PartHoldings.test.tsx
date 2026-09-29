import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createTestQueryClient, renderInRouter } from "../../test/render";
import { aPartHolding, aRevisionRef, respondWithPartHoldings } from "../../test/server";
import { PartHoldings } from "./PartHoldings";

const PART = "0199cccc-0000-7000-8000-000000000001";

function render() {
  renderInRouter(<PartHoldings partId={PART} />, { queryClient: createTestQueryClient() });
}

describe("PartHoldings", () => {
  it("lists each build holding the part, linking to it, with reserved or consumed", async () => {
    respondWithPartHoldings(PART, [
      aPartHolding({
        revision: aRevisionRef({
          id: "0199eeee-0000-7000-8000-00000000000a",
          project_name: "Greenhouse controller",
          label: "A",
          summary: "breadboard",
        }),
        reserved: 3,
        consumed: 0,
      }),
      aPartHolding({
        revision: aRevisionRef({
          id: "0199eeee-0000-7000-8000-00000000000b",
          project_name: "Weather station",
          label: "B",
          summary: null,
        }),
        reserved: 0,
        consumed: 2,
      }),
    ]);
    render();

    const section = await screen.findByRole("region", { name: "Held for builds" });
    expect(
      await within(section).findByRole("link", { name: /Greenhouse controller/ }),
    ).toBeInTheDocument();
    expect(within(section).getByText("3 reserved")).toBeInTheDocument();
    expect(within(section).getByRole("link", { name: /Weather station/ })).toBeInTheDocument();
    expect(within(section).getByText("2 in the build")).toBeInTheDocument();
  });

  it("says no build holds any when the part is held by none", async () => {
    respondWithPartHoldings(PART, []);
    render();

    const section = await screen.findByRole("region", { name: "Held for builds" });
    expect(await within(section).findByText("No build holds any of this.")).toBeInTheDocument();
    expect(within(section).queryByRole("link")).not.toBeInTheDocument();
  });
});
