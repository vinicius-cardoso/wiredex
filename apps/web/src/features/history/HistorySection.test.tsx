import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { renderInRouter } from "../../test/render";
import { aChange, acceptRestores, respondWithTimeline, server } from "../../test/server";
import { HistorySection } from "./HistorySection";

const PART_ID = "0199aaaa-0000-7000-8000-0000000000f1";

function renderSection() {
  return renderInRouter(<HistorySection kind="part" recordId={PART_ID} />);
}

describe("HistorySection", () => {
  it("asks for nothing until it is opened", async () => {
    const asked = respondWithTimeline("part", PART_ID, [aChange()]);
    renderSection();

    const toggle = await screen.findByRole("button", { name: "Show history" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("region", { name: "History" })).toBeVisible();
    expect(asked).toEqual([]);
  });

  it("opens on the record's changes, without naming the record again", async () => {
    const asked = respondWithTimeline("part", PART_ID, [aChange()]);
    renderSection();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Show history" }));

    const list = await screen.findByRole("list", { name: "Changes" });
    expect(within(list).getAllByRole("listitem")[0]).toHaveTextContent("Edited");
    expect(within(list).queryByRole("link")).toBeNull();
    // A record's page keeps its history in one column, under the rest of the page.
    expect(list).not.toHaveClass("xl:grid-cols-2");
    expect(asked).toEqual([`part:${PART_ID}`]);
    expect(screen.getByRole("button", { name: "Hide history" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText(/History starts with Wiredex 0\.8\.0/)).toBeVisible();
  });

  it("folds each change until it is opened", async () => {
    respondWithTimeline("part", PART_ID, [aChange()]);
    renderSection();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Show history" }));

    const [change] = within(await screen.findByRole("list", { name: "Changes" })).getAllByRole(
      "listitem",
    );
    expect(change).toHaveTextContent("Part number: RC0805FR-074K7 → RC0805FR-074K7L");
    expect(screen.queryByRole("button", { name: /Restore/ })).toBeNull();
    await user.click(within(change as HTMLElement).getByRole("button", { name: "Expand" }));
    expect(within(change as HTMLElement).getByText("Part number")).toBeVisible();
  });

  it("restores a version from the page", async () => {
    respondWithTimeline("part", PART_ID, [aChange()]);
    const restored = acceptRestores();
    renderSection();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Show history" }));
    await user.click(await screen.findByRole("button", { name: "Expand" }));
    await user.click(
      screen.getByRole("button", { name: "Restore the version before this change" }),
    );
    await user.click(screen.getByRole("button", { name: "Restore" }));

    expect(await screen.findByText("Restored. The restore is the newest change.")).toBeVisible();
    expect(restored).toEqual([41]);
  });

  it("says so when the history can't be read", async () => {
    server.use(
      http.get("*/api/history/:kind/:recordId", () => HttpResponse.json({}, { status: 500 })),
    );
    renderSection();

    await userEvent.setup().click(await screen.findByRole("button", { name: "Show history" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The history couldn't be loaded.");
  });
});
