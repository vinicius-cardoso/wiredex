import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ProjectDetails } from "@wiredex/api-client";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  aBom,
  acceptProjectWrites,
  aProject,
  aRevision,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithBom,
} from "../../test/server";

const PROJECT_ID = "0199eeee-0000-7000-8000-000000000001";
const breadboard = aRevision({
  id: "0199eeee-0000-7000-8000-00000000000a",
  label: "A",
  summary: "breadboard",
});
const perfboard = aRevision({
  id: "0199eeee-0000-7000-8000-00000000000b",
  label: "B",
  summary: "perfboard",
  forked_from: breadboard.id,
  created_at: "2026-09-27T11:00:00Z",
});
const twoRevisions = aProject({
  id: PROJECT_ID,
  revisions: [breadboard, perfboard],
  latest_revision_id: perfboard.id,
  next_label: "C",
});

function renderAt(project: ProjectDetails, path: string) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  const writes = acceptProjectWrites(project);
  const queryClient = createTestQueryClient();
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [path] }));
  renderWithProviders(<RouterProvider router={router} />, { queryClient });
  return { router, writes };
}

describe("RevisionPanel", () => {
  it("edits a revision and keeps it open", async () => {
    const { router, writes } = renderAt(
      twoRevisions,
      `/projects/${PROJECT_ID}/revisions/${breadboard.id}`,
    );
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Revision A – breadboard" });
    await user.click(within(panel).getByRole("button", { name: "Edit revision" }));
    const dialog = screen.getByRole("dialog", { name: "Edit revision A – breadboard" });
    const summary = within(dialog).getByRole("textbox", { name: "Summary" });
    await user.clear(summary);
    await user.type(summary, "breadboard, v2 sensor");
    await user.type(within(dialog).getByRole("textbox", { name: "Notes" }), "New BME280.");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(
      await screen.findByRole("region", { name: "Revision A – breadboard, v2 sensor" }),
    ).toHaveTextContent("New BME280.");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(writes.revisionEdits).toEqual([
      {
        revisionId: breadboard.id,
        body: { label: "A", summary: "breadboard, v2 sensor", notes: "New BME280." },
      },
    ]);
    expect(router.state.location.pathname).toBe(
      `/projects/${PROJECT_ID}/revisions/${breadboard.id}`,
    );
  });

  it("forks a revision with the suggested label, and opens the fork", async () => {
    const { writes } = renderAt(twoRevisions, `/projects/${PROJECT_ID}/revisions/${breadboard.id}`);
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Revision A – breadboard" });
    await user.click(within(panel).getByRole("button", { name: "Fork" }));
    const dialog = screen.getByRole("dialog", { name: "Fork revision A – breadboard" });
    expect(within(dialog).getByRole("textbox", { name: "Label" })).toHaveValue("C");
    // Enter in the summary submits, as the dialog promises (requirement 10.6).
    await user.type(within(dialog).getByRole("textbox", { name: "Summary" }), "PCB{Enter}");

    const fork = await screen.findByRole("region", { name: "Revision C – PCB" });
    expect(within(fork).getByRole("link", { name: "A" })).toBeInTheDocument();
    expect(writes.forks).toEqual([
      { source: breadboard.id, body: { label: "C", summary: "PCB", notes: null } },
    ]);
  });

  it("deletes a revision after asking, and lands on the latest", async () => {
    const { router, writes } = renderAt(
      twoRevisions,
      `/projects/${PROJECT_ID}/revisions/${perfboard.id}`,
    );
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Revision B – perfboard" });
    await user.click(within(panel).getByRole("button", { name: "Delete revision" }));
    const question = within(panel).getByRole("group", {
      name: "Delete revision B – perfboard?",
    });
    await user.click(within(question).getByRole("button", { name: "Yes, delete it" }));

    expect(
      await screen.findByRole("region", { name: "Revision A – breadboard" }),
    ).toBeInTheDocument();
    expect(writes.deletions).toEqual([perfboard.id]);
    expect(router.state.location.pathname).toBe(`/projects/${PROJECT_ID}`);
  });

  it("shows the revision's bill of materials before its files", async () => {
    renderAt(twoRevisions, `/projects/${PROJECT_ID}/revisions/${breadboard.id}`);
    respondWithBom(aBom({}, { revision_id: breadboard.id }));

    const panel = await screen.findByRole("region", { name: "Revision A – breadboard" });
    const bom = within(panel).getByRole("region", { name: "Bill of materials" });
    expect(
      await within(bom).findByRole("table", { name: "Lines of the bill of materials" }),
    ).toHaveTextContent("R1–R4");
    const files = within(panel).getByRole("region", { name: "Files" });
    expect(bom.compareDocumentPosition(files) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps a revision that holds stock, saying to cancel or dismantle it first", async () => {
    const reserved = aRevision({
      id: breadboard.id,
      label: "A",
      summary: "breadboard",
      status: "reserved",
    });
    const project = aProject({
      id: PROJECT_ID,
      revisions: [reserved, perfboard],
      latest_revision_id: reserved.id,
    });
    const { writes } = renderAt(project, `/projects/${PROJECT_ID}/revisions/${reserved.id}`);
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Revision A – breadboard" });
    const remove = within(panel).getByRole("button", { name: "Delete revision" });
    // A project with two revisions would normally let a draft go; a reserved one can't,
    // and the holds-stock reason wins (requirement 13.12).
    expect(remove).toHaveAttribute("aria-disabled", "true");
    expect(remove).toHaveAccessibleDescription(
      "This revision holds stock; cancel the reservation or dismantle the build before deleting it.",
    );
    await user.click(remove);

    expect(within(panel).queryByRole("group")).not.toBeInTheDocument();
    expect(writes.deletions).toEqual([]);
  });

  it("keeps the only revision, saying why its delete is unavailable", async () => {
    const { writes } = renderAt(
      aProject({ id: PROJECT_ID, revisions: [breadboard] }),
      `/projects/${PROJECT_ID}`,
    );
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Revision A – breadboard" });
    const remove = within(panel).getByRole("button", { name: "Delete revision" });
    expect(remove).toHaveAttribute("aria-disabled", "true");
    expect(remove).toHaveAccessibleDescription(
      "A project keeps at least one revision; delete the project instead.",
    );
    await user.click(remove);

    expect(within(panel).queryByRole("group")).not.toBeInTheDocument();
    expect(writes.deletions).toEqual([]);
  });
});
