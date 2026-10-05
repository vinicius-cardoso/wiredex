import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { RunsOn } from "@wiredex/api-client";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderInRouter, renderWithProviders } from "../../test/render";
import {
  acceptFirmwareWrites,
  acceptProjectWrites,
  aFirmware,
  aFirmwareSummary,
  aProject,
  aRevision,
  aRevisionRef,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithFirmwareList,
  respondWithRevisionFirmware,
  respondWithRevisionRef,
} from "../../test/server";
import { RevisionFirmwareSection } from "./RevisionFirmwareSection";

const PROJECT_ID = "0199eeee-0000-7000-8000-000000000001";
const REVISION_ID = "0199eeee-0000-7000-8000-00000000000a";
const WEATHER_ID = "0199ffff-0000-7000-8000-000000000001";
const GREENHOUSE_ID = "0199ffff-0000-7000-8000-000000000002";
const PICO_ID = "0199ffff-0000-7000-8000-000000000003";

const onBreadboard: RunsOn = {
  revision_id: REVISION_ID,
  project_id: PROJECT_ID,
  project_name: "Weather station",
  label: "A",
  summary: "breadboard",
};

function optionsOf(select: HTMLElement) {
  return within(select)
    .getAllByRole("option")
    .map((option) => option.textContent);
}

describe("RevisionFirmwareSection", () => {
  it("shows each firmware the revision runs with its latest release, linking to its page", async () => {
    const weather = aFirmwareSummary({
      id: WEATHER_ID,
      latest_release: { id: "0199ffff-0000-7000-8000-0000000000a2", version: "1.1.0" },
      versions: 3,
      drafts: 1,
    });
    const greenhouse = aFirmwareSummary({ id: GREENHOUSE_ID, name: "Greenhouse controller" });
    respondWithRevisionFirmware(REVISION_ID, [greenhouse, weather]);
    respondWithFirmwareList([weather, greenhouse]);
    renderInRouter(<RevisionFirmwareSection revisionId={REVISION_ID} />);

    const section = await screen.findByRole("region", { name: "Firmware" });
    const sketch = await within(section).findByRole("link", { name: "Weather station" });
    expect(sketch).toHaveAttribute("href", `/firmware/${WEATHER_ID}`);
    expect(sketch.closest("li")).toHaveTextContent("Latest release 1.1.0");
    const controller = within(section).getByRole("link", { name: "Greenhouse controller" });
    expect(controller).toHaveAttribute("href", `/firmware/${GREENHOUSE_ID}`);
    expect(controller.closest("li")).toHaveTextContent("No release yet");
    // Every firmware of the workspace runs here already, so there is nothing left to link.
    expect(within(section).queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("links a firmware chosen from the others, and unlinks one", async () => {
    const writes = acceptFirmwareWrites(
      [
        aFirmware({ id: WEATHER_ID, runs_on: [onBreadboard] }),
        aFirmware({ id: PICO_ID, name: "Pico blink" }),
        aFirmware({ id: GREENHOUSE_ID, name: "Greenhouse controller" }),
      ],
      { revisions: [onBreadboard] },
    );
    renderInRouter(<RevisionFirmwareSection revisionId={REVISION_ID} />);
    const user = userEvent.setup();

    const section = await screen.findByRole("region", { name: "Firmware" });
    await within(section).findByRole("link", { name: "Weather station" });
    const select = await within(section).findByRole("combobox", { name: "Firmware to link" });
    // The firmware it doesn't run yet, by name.
    expect(optionsOf(select)).toEqual(["Greenhouse controller", "Pico blink"]);
    await user.selectOptions(select, "Pico blink");
    await user.click(within(section).getByRole("button", { name: "Link" }));

    expect(await within(section).findByRole("link", { name: "Pico blink" })).toBeInTheDocument();
    expect(writes.links).toEqual([{ firmwareId: PICO_ID, revisionId: REVISION_ID }]);
    expect(optionsOf(select)).toEqual(["Greenhouse controller"]);

    await user.click(within(section).getByRole("button", { name: "Unlink Weather station" }));

    await waitFor(() =>
      expect(within(section).queryByRole("link", { name: "Weather station" })).toBeNull(),
    );
    expect(writes.unlinks).toEqual([{ firmwareId: WEATHER_ID, revisionId: REVISION_ID }]);
    expect(optionsOf(select)).toEqual(["Greenhouse controller", "Weather station"]);
    expect(writes.firmware().find((firmware) => firmware.id === WEATHER_ID)?.runs_on).toEqual([]);
  });

  it("sits after the overview and before the bill of materials, and starts a new firmware running on the revision", async () => {
    respondWithApiVersion("0.0.0");
    respondAsLoggedIn();
    const breadboard = aRevision({ id: REVISION_ID, label: "A", summary: "breadboard" });
    acceptProjectWrites(aProject({ id: PROJECT_ID, revisions: [breadboard] }));
    respondWithRevisionRef(aRevisionRef({ id: REVISION_ID, label: "A", summary: "breadboard" }));
    const queryClient = createTestQueryClient();
    const router = createAppRouter(
      queryClient,
      createMemoryHistory({ initialEntries: [`/projects/${PROJECT_ID}/revisions/${REVISION_ID}`] }),
    );
    renderWithProviders(<RouterProvider router={router} />, { queryClient });
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Revision A – breadboard" });
    const section = within(panel).getByRole("region", { name: "Firmware" });
    // A short block, so it shares the overview's row; the wide tables follow.
    const overview = within(panel).getByRole("region", { name: "Overview" });
    const bom = within(panel).getByRole("region", { name: "Bill of materials" });
    expect(
      overview.compareDocumentPosition(section) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(section.compareDocumentPosition(bom) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(
      within(section).getByRole("heading", { level: 3, name: "Firmware" }),
    ).toBeInTheDocument();
    expect(
      await within(section).findByText("No firmware runs on this revision yet."),
    ).toBeInTheDocument();

    await user.click(within(section).getByRole("link", { name: "New firmware" }));

    expect(await screen.findByRole("heading", { name: "New firmware" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/firmware/new");
    expect(router.state.location.search).toEqual({ revision: REVISION_ID });
    expect(
      await screen.findByRole("link", { name: "Weather station · A – breadboard" }),
    ).toBeInTheDocument();
  });
});
