import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test/render";
import { acceptProjectWrites, aProject, aRevision } from "../../test/server";
import { EditRevisionDialog, ForkRevisionDialog, NewRevisionDialog } from "./RevisionDialogs";

const breadboard = aRevision({
  id: "0199eeee-0000-7000-8000-00000000000a",
  label: "A",
  summary: "breadboard",
});
const perfboard = aRevision({
  id: "0199eeee-0000-7000-8000-00000000000b",
  label: "B",
  summary: "perfboard",
  created_at: "2026-09-27T11:00:00Z",
});
const project = aProject({
  revisions: [breadboard, perfboard],
  latest_revision_id: perfboard.id,
  next_label: "C",
});

describe("RevisionDialogs", () => {
  it("puts a label another revision holds on the label, as the API's 409 says", async () => {
    acceptProjectWrites(project);
    const onForked = vi.fn();
    renderWithProviders(
      <ForkRevisionDialog
        project={project}
        source={breadboard}
        onClose={() => undefined}
        onForked={onForked}
      />,
    );
    const user = userEvent.setup();

    const label = screen.getByRole("textbox", { name: "Label" });
    await user.clear(label);
    await user.type(label, "b{Enter}");

    expect(await screen.findByText("Weather station already has a revision b")).toBeVisible();
    expect(label).toHaveAttribute("aria-invalid", "true");
    expect(label).toHaveAccessibleDescription(/already has a revision b/);
    expect(onForked).not.toHaveBeenCalled();
  });

  it("leaves an emptied label to the API's suggestion", async () => {
    const writes = acceptProjectWrites(project);
    const onCreated = vi.fn();
    renderWithProviders(
      <NewRevisionDialog project={project} onClose={() => undefined} onCreated={onCreated} />,
    );
    const user = userEvent.setup();

    await user.clear(screen.getByRole("textbox", { name: "Label" }));
    await user.type(screen.getByRole("textbox", { name: "Notes" }), "  Moved the sensor.  ");
    await user.click(screen.getByRole("button", { name: "Add revision" }));

    await vi.waitFor(() => expect(onCreated).toHaveBeenCalledOnce());
    expect(writes.additions).toEqual([{ label: null, summary: null, notes: "Moved the sensor." }]);
    expect(onCreated.mock.calls[0]?.[0]).toMatchObject({ label: "C" });
  });

  it("refuses a label outside the rules before anything is sent", async () => {
    const writes = acceptProjectWrites(project);
    renderWithProviders(<EditRevisionDialog revision={breadboard} onClose={() => undefined} />);
    const user = userEvent.setup();

    const dialog = screen.getByRole("dialog", { name: "Edit revision A – breadboard" });
    const label = within(dialog).getByRole("textbox", { name: "Label" });
    await user.clear(label);
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(label).toHaveAccessibleDescription(/A revision needs a label\./);

    await user.type(label, "-rev c");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(label).toHaveAccessibleDescription(/starting and ending with a letter or a digit/);
    expect(writes.revisionEdits).toEqual([]);
  });

  it("closes on Cancel", async () => {
    const onClose = vi.fn();
    renderWithProviders(<EditRevisionDialog revision={breadboard} onClose={onClose} />);

    await userEvent.setup().click(screen.getByRole("button", { name: "Cancel" }));

    expect(onClose).toHaveBeenCalledOnce();
  });
});
