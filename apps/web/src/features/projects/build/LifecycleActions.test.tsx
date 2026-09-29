import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { RevisionStatus } from "@wiredex/api-client";
import { describe, expect, it } from "vitest";
import { createTestQueryClient, renderInRouter } from "../../../test/render";
import {
  aBom,
  acceptTransitions,
  aLifecycle,
  aRevision,
  respondWithBom,
  respondWithLifecycle,
} from "../../../test/server";
import { LifecycleActions } from "./LifecycleActions";

const REVISION_ID = "0199eeee-0000-7000-8000-00000000000a";

const TRANSITIONS: Record<RevisionStatus, string[]> = {
  draft: ["reserve"],
  reserved: ["cancel", "build"],
  built: ["dismantle"],
  dismantled: [],
};

function renderAt(status: RevisionStatus) {
  const revision = aRevision({ id: REVISION_ID, status });
  respondWithLifecycle(
    REVISION_ID,
    aLifecycle({ status, transitions: TRANSITIONS[status] as never }),
  );
  const calls = acceptTransitions(revision);
  const queryClient = createTestQueryClient();
  renderInRouter(<LifecycleActions revision={revision} />, { queryClient });
  return { calls };
}

describe("LifecycleActions", () => {
  it("offers only Reserve parts for a draft", async () => {
    renderAt("draft");
    expect(await screen.findByRole("button", { name: "Reserve parts" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Build" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dismantle" })).not.toBeInTheDocument();
  });

  it("offers Build and Cancel reservation for a reserved revision, and builds by keyboard", async () => {
    const { calls } = renderAt("reserved");
    const user = userEvent.setup();

    expect(await screen.findByRole("button", { name: "Cancel reservation" })).toBeInTheDocument();
    const build = screen.getByRole("button", { name: "Build" });

    // Tab to the Build button and confirm in place with the keyboard alone (requirement 13.15).
    build.focus();
    await user.keyboard("{Enter}");
    const question = screen.getByRole("group", { name: "Build revision A?" });
    expect(within(question).getByRole("button", { name: "Build it" })).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(calls.builds).toEqual([REVISION_ID]);
  });

  it("cancels a reservation after asking in place", async () => {
    const { calls } = renderAt("reserved");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Cancel reservation" }));
    const question = screen.getByRole("group", { name: "Cancel the reservation on revision A?" });
    await user.click(within(question).getByRole("button", { name: "Cancel it" }));

    expect(calls.cancels).toEqual([REVISION_ID]);
  });

  it("opens the reserve dialog for a draft", async () => {
    renderAt("draft");
    respondWithBom(aBom({ parts: [] }, { revision_id: REVISION_ID }));
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Reserve parts" }));
    expect(await screen.findByRole("dialog", { name: "Reserve parts" })).toBeInTheDocument();
  });

  it("opens the dismantle dialog for a built revision", async () => {
    renderAt("built");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Dismantle" }));
    expect(screen.getByRole("dialog", { name: "Dismantle the build" })).toBeInTheDocument();
  });

  it("shows a fork note and no action for a dismantled revision", async () => {
    renderAt("dismantled");
    expect(
      await screen.findByText("This build is dismantled; fork it to build it again."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
