import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { HistoryChange } from "@wiredex/api-client";
import { HttpResponse, http } from "msw";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { createTestQueryClient, renderInRouter } from "../../test/render";
import {
  aChange,
  acceptRestores,
  pageAsked,
  pagedBy,
  respondWithTimeline,
  server,
} from "../../test/server";
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

  it("is a full-width block that holds its own toggle", async () => {
    respondWithTimeline("part", PART_ID, [aChange()]);
    renderSection();

    const region = await screen.findByRole("region", { name: "History" });
    expect(region).toHaveClass("col-span-full");
    expect(within(region).getByRole("heading", { level: 2, name: "History" })).toBeVisible();
    expect(within(region).getByRole("button", { name: "Show history" })).toBeVisible();
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
    expect(asked).toEqual([{ record: `part:${PART_ID}`, page: 1, page_size: 25 }]);
    expect(screen.getByRole("button", { name: "Hide history" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText(/History starts with Wiredex 0\.8\.0/)).toBeVisible();
    expect(
      within(screen.getByRole("navigation", { name: "Pages of this history" })).getByText(
        "1–1 of 1",
      ),
    ).toBeVisible();
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

describe("HistorySection in pages", () => {
  const OTHER_ID = "0199aaaa-0000-7000-8000-0000000000f9";
  const many = (count: number, from: number): HistoryChange[] =>
    Array.from({ length: count }, (_, index) => aChange({ id: from - index, restorable: false }));

  function bar(): HTMLElement {
    return screen.getByRole("navigation", { name: "Pages of this history" });
  }

  function changeItems(): HTMLElement[] {
    const list = screen.getByRole("list", { name: "Changes" });
    return within(list)
      .getAllByRole("listitem")
      .filter((item) => item.parentElement === list);
  }

  it("pages in place: the request asks for page 2 and the address stays as it was", async () => {
    const asked = respondWithTimeline("part", PART_ID, many(30, 500));
    const { router } = renderSection();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Show history" }));
    expect(await within(bar()).findByText("1–25 of 30")).toBeVisible();
    expect(screen.queryByText(/History starts with/)).toBeNull();

    await user.click(within(bar()).getByRole("button", { name: "Next page" }));

    expect(await within(bar()).findByText("26–30 of 30")).toBeVisible();
    expect(changeItems()).toHaveLength(5);
    expect(asked.at(-1)).toEqual({ record: `part:${PART_ID}`, page: 2, page_size: 25 });
    expect(router.state.location.pathname).toBe("/");
    expect(router.state.location.search).toEqual({});
    expect(screen.getByText(/History starts with/)).toBeVisible();
  });

  it("starts another record's history at its first page", async () => {
    const timelines: Record<string, HistoryChange[]> = {
      [PART_ID]: many(30, 500),
      [OTHER_ID]: many(35, 900),
    };
    const asked: { record: string; page: number }[] = [];
    server.use(
      http.get("*/api/history/:kind/:recordId", ({ params, request }) => {
        const { page, page_size } = pageAsked(request);
        asked.push({ record: String(params.recordId), page });
        const { items, ...served } = pagedBy(
          timelines[String(params.recordId)] ?? [],
          page,
          page_size,
        );
        return HttpResponse.json({ changes: items, ...served });
      }),
    );
    function Switcher() {
      const [recordId, setRecordId] = useState(PART_ID);
      return (
        <>
          <button type="button" onClick={() => setRecordId(OTHER_ID)}>
            Other part
          </button>
          <HistorySection kind="part" recordId={recordId} />
        </>
      );
    }
    renderInRouter(<Switcher />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Show history" }));
    await within(
      await screen.findByRole("navigation", { name: "Pages of this history" }),
    ).findByText("1–25 of 30");
    await user.click(within(bar()).getByRole("button", { name: "Page 2" }));
    expect(await within(bar()).findByText("26–30 of 30")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Other part" }));

    expect(await within(bar()).findByText("1–25 of 35")).toBeVisible();
    expect(asked.at(-1)).toEqual({ record: OTHER_ID, page: 1 });
    expect(asked).not.toContainEqual({ record: OTHER_ID, page: 2 });
  });

  it("shows the last page when the page it holds is past the end", async () => {
    let held = many(30, 500);
    const asked = respondWithTimeline("part", PART_ID, () => held);
    const queryClient = createTestQueryClient();
    renderInRouter(<HistorySection kind="part" recordId={PART_ID} />, { queryClient });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Show history" }));
    await user.click(
      within(await screen.findByRole("navigation", { name: "Pages of this history" })).getByRole(
        "button",
        { name: "Last page" },
      ),
    );
    expect(await within(bar()).findByText("26–30 of 30")).toBeVisible();

    // The record's history shrinks to one page, as a demo reset would leave it.
    held = many(3, 500);
    await queryClient.invalidateQueries();

    // The page past the end is answered as the last one, and the section moves to it. That
    // takes two requests: page 2 again, answered as page 1, then page 1 itself after the clamp,
    // with page 1's old answer shown from the cache in between. So wait on the end state, page 1
    // asked and answered, with waitFor's 3 s rather than expect.poll's 1 s, which a coverage
    // run outlasts.
    await waitFor(() => {
      expect(asked.at(-1)).toEqual({ record: `part:${PART_ID}`, page: 1, page_size: 25 });
      expect(within(bar()).getByText("1–3 of 3")).toBeVisible();
      expect(changeItems()).toHaveLength(3);
    });
    expect(within(bar()).getByRole("button", { name: "Page 1" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
