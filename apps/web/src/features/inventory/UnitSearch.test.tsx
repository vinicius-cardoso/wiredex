import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createTestQueryClient, renderInRouter } from "../../test/render";
import {
  aUnit,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithUnitSearch,
} from "../../test/server";
import { UnitSearch } from "./UnitSearch";

const board = aUnit({
  id: "0199dddd-0000-7000-8000-0000000000c1",
  code: "WX-U-0042",
  serial: "SN-1",
  mac: "aa:bb:cc:dd:ee:ff",
});

function renderSearch(units = [board]) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  const asked = respondWithUnitSearch(units);
  renderInRouter(<UnitSearch />, { queryClient: createTestQueryClient() });
  return asked;
}

describe("UnitSearch", () => {
  it("prompts before a term is typed and asks nothing", async () => {
    const asked = renderSearch();

    expect(await screen.findByText(/Type a code, serial or MAC/)).toBeInTheDocument();
    expect(asked).toEqual([]);
  });

  it("finds a unit by its MAC and links to its page", async () => {
    renderSearch();
    const user = userEvent.setup();

    await user.type(
      await screen.findByRole("searchbox", { name: "Search units" }),
      "aa:bb:cc:dd:ee:ff",
    );

    const row = await screen.findByRole("row", { name: /WX-U-0042/ });
    expect(within(row).getByRole("link", { name: "WX-U-0042" })).toHaveAttribute(
      "href",
      `/units/${board.id}`,
    );
  });

  it("finds a unit by its code", async () => {
    renderSearch();
    const user = userEvent.setup();

    await user.type(await screen.findByRole("searchbox", { name: "Search units" }), "WX-U-0042");

    expect(await screen.findByRole("link", { name: "WX-U-0042" })).toBeInTheDocument();
  });

  it("says when nothing matches", async () => {
    renderSearch();
    const user = userEvent.setup();

    await user.type(await screen.findByRole("searchbox", { name: "Search units" }), "nothing");

    expect(await screen.findByText("No unit matches that.")).toBeInTheDocument();
  });
});
