import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { RunsOn } from "@wiredex/api-client";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  acceptFirmwareWrites,
  aFirmware,
  aRevisionRef,
  NEW_FIRMWARE_ID,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithRevisionRef,
} from "../../test/server";

const breadboard = aRevisionRef({
  id: "0199eeee-0000-7000-8000-00000000000a",
  label: "A",
  summary: "breadboard",
  project_id: "0199eeee-0000-7000-8000-000000000001",
  project_name: "Weather station",
});
const runsOnBreadboard: RunsOn = {
  revision_id: breadboard.id,
  project_id: breadboard.project_id,
  project_name: breadboard.project_name,
  label: breadboard.label,
  summary: breadboard.summary,
};

function renderNewFirmware(path = "/firmware/new") {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  respondWithRevisionRef(breadboard);
  const writes = acceptFirmwareWrites([aFirmware({ name: "Greenhouse controller" })], {
    revisions: [runsOnBreadboard],
  });
  const queryClient = createTestQueryClient();
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [path] }));
  renderWithProviders(<RouterProvider router={router} />, { queryClient });
  return { router, writes };
}

describe("NewFirmwarePage", () => {
  it("saves the firmware and opens its page", async () => {
    const { router, writes } = renderNewFirmware();
    const user = userEvent.setup();

    await user.type(await screen.findByRole("textbox", { name: "Name" }), "  Pico   blink ");
    await user.type(screen.getByRole("textbox", { name: "Board target" }), " RPI_PICO ");
    await user.selectOptions(screen.getByRole("combobox", { name: "Framework" }), "MicroPython");
    await user.type(
      screen.getByRole("textbox", { name: "Description" }),
      "Blinks the on-board LED.{Enter}Then fades it.",
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByRole("heading", { name: "Pico blink", level: 1 }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(`/firmware/${NEW_FIRMWARE_ID}`);
    expect(screen.getByText("RPI_PICO")).toBeInTheDocument();
    expect(screen.getByText("MicroPython")).toBeInTheDocument();
    expect(writes.creates).toEqual([
      {
        name: "Pico blink",
        target: "RPI_PICO",
        framework: "micropython",
        description: "Blinks the on-board LED.\nThen fades it.",
        revision_id: null,
      },
    ]);
  });

  it("starts a firmware for a revision, naming it first and sending its id", async () => {
    const { writes } = renderNewFirmware(`/firmware/new?revision=${breadboard.id}`);
    const user = userEvent.setup();

    const named = await screen.findByRole("link", { name: "Weather station · A – breadboard" });
    expect(named).toHaveAttribute(
      "href",
      `/projects/${breadboard.project_id}/revisions/${breadboard.id}`,
    );
    expect(named.closest("p")).toHaveTextContent("It will run on Weather station · A – breadboard");
    await user.type(screen.getByRole("textbox", { name: "Name" }), "Weather station");
    await user.type(screen.getByRole("textbox", { name: "Board target" }), "esp32:esp32:esp32");
    await user.click(screen.getByRole("button", { name: "Save" }));

    const runsOn = await screen.findByRole("region", { name: "Runs on" });
    expect(
      within(runsOn).getByRole("link", { name: "Weather station · A – breadboard" }),
    ).toBeInTheDocument();
    expect(writes.creates).toEqual([
      {
        name: "Weather station",
        target: "esp32:esp32:esp32",
        framework: "arduino",
        description: null,
        revision_id: breadboard.id,
      },
    ]);
  });

  it("says so when the revision isn't in the workspace", async () => {
    renderNewFirmware("/firmware/new?revision=0199eeee-0000-7000-8000-0000000000ff");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That revision isn't in this workspace, so no firmware can be started for it.",
    );
    expect(
      screen.getByRole("link", { name: "Start one that runs on no revision" }),
    ).toHaveAttribute("href", "/firmware/new");
  });

  it("asks for a name and a board target before sending anything", async () => {
    const { writes } = renderNewFirmware();
    const user = userEvent.setup();

    const name = await screen.findByRole("textbox", { name: "Name" });
    await user.type(name, "   ");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("A firmware needs a name.")).toBeInTheDocument();
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveAccessibleDescription("A firmware needs a name.");
    expect(screen.getByRole("textbox", { name: "Board target" })).toHaveAccessibleDescription(
      "A firmware needs the board it targets.",
    );
    expect(writes.creates).toEqual([]);
  });

  it("marks a name another firmware holds on the name", async () => {
    const { router, writes } = renderNewFirmware();
    const user = userEvent.setup();

    const name = await screen.findByRole("textbox", { name: "Name" });
    await user.type(name, "greenhouse CONTROLLER");
    await user.type(screen.getByRole("textbox", { name: "Board target" }), "esp32:esp32:esp32");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(name).toHaveAccessibleDescription(
        "Another firmware is already named greenhouse CONTROLLER.",
      ),
    );
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(writes.creates).toHaveLength(1);
    expect(router.state.location.pathname).toBe("/firmware/new");
  });

  it("goes back to the list on Cancel", async () => {
    const { router } = renderNewFirmware();

    await userEvent.setup().click(await screen.findByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/firmware"));
  });
});
