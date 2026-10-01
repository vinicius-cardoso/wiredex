import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  acceptFirmwareWrites,
  aFirmware,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithFirmware,
} from "../../test/server";

const FIRMWARE_ID = "0199ffff-0000-7000-8000-000000000001";
const PROJECT_ID = "0199eeee-0000-7000-8000-000000000001";

const weatherStation = aFirmware({
  id: FIRMWARE_ID,
  name: "Weather station",
  target: "esp32:esp32:esp32",
  framework: "arduino",
  description: "Reads the BME280 at 0x76.\nSleeps between readings.",
  runs_on: [
    {
      revision_id: "0199eeee-0000-7000-8000-00000000000a",
      project_id: PROJECT_ID,
      project_name: "Weather station",
      label: "A",
      summary: "breadboard",
    },
    {
      revision_id: "0199eeee-0000-7000-8000-00000000000b",
      project_id: PROJECT_ID,
      project_name: "Weather station",
      label: "B",
      summary: null,
    },
  ],
});

/**
 * The weather station's page, unless `answered`: the test has answered the page itself, through
 * `respondWithFirmware` or `acceptFirmwareWrites`, and a later handler would win over it.
 */
function renderAt(path: string, { answered = false } = {}) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  if (!answered) respondWithFirmware(weatherStation);
  const queryClient = createTestQueryClient();
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [path] }));
  renderWithProviders(<RouterProvider router={router} />, { queryClient });
  return router;
}

describe("FirmwarePage", () => {
  it("shows the details and links each revision it runs on", async () => {
    renderAt(`/firmware/${FIRMWARE_ID}`);

    expect(
      await screen.findByRole("heading", { name: "Weather station", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByText("esp32:esp32:esp32")).toBeInTheDocument();
    expect(screen.getByText("Arduino")).toBeInTheDocument();
    expect(screen.getByText(/Reads the BME280 at 0x76/)).toHaveTextContent(
      "Reads the BME280 at 0x76. Sleeps between readings.",
    );
    const runsOn = screen.getByRole("region", { name: "Runs on" });
    const links = within(runsOn).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Weather station · A – breadboard",
      "Weather station · B",
    ]);
    expect(links[0]).toHaveAttribute(
      "href",
      `/projects/${PROJECT_ID}/revisions/0199eeee-0000-7000-8000-00000000000a`,
    );
    expect(screen.getByRole("link", { name: "← Firmware" })).toHaveAttribute("href", "/firmware");
  });

  it("says so when it runs on no revision", async () => {
    respondWithFirmware(aFirmware({ id: FIRMWARE_ID, name: "Pico blink", runs_on: [] }));
    renderAt(`/firmware/${FIRMWARE_ID}`, { answered: true });

    const runsOn = await screen.findByRole("region", { name: "Runs on" });
    expect(runsOn).toHaveTextContent("No revision yet.");
    expect(within(runsOn).queryByRole("link")).not.toBeInTheDocument();
  });

  it("says so when the firmware can't be loaded", async () => {
    renderAt("/firmware/0199ffff-0000-7000-8000-0000000000ff");

    expect(await screen.findByRole("alert")).toHaveTextContent("The firmware couldn't be loaded.");
  });

  it("edits the firmware in place and shows the saved details", async () => {
    const writes = acceptFirmwareWrites([weatherStation]);
    renderAt(`/firmware/${FIRMWARE_ID}`, { answered: true });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Edit firmware" }));
    expect(
      screen.getByRole("heading", { name: "Edit Weather station", level: 1 }),
    ).toBeInTheDocument();
    // The form takes the header's place only: what it runs on stays in view.
    expect(screen.getByRole("region", { name: "Runs on" })).toBeInTheDocument();
    const name = screen.getByRole("textbox", { name: "Name" });
    expect(name).toHaveValue("Weather station");
    expect(screen.getByRole("combobox", { name: "Framework" })).toHaveValue("arduino");
    await user.clear(name);
    await user.type(name, "Weather station mk2");
    await user.selectOptions(screen.getByRole("combobox", { name: "Framework" }), "PlatformIO");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByRole("heading", { name: "Weather station mk2", level: 1 }),
    ).toBeInTheDocument();
    expect(await screen.findByText("PlatformIO")).toBeInTheDocument();
    expect(writes.edits).toEqual([
      {
        firmwareId: FIRMWARE_ID,
        body: {
          name: "Weather station mk2",
          target: "esp32:esp32:esp32",
          framework: "platformio",
          description: "Reads the BME280 at 0x76.\nSleeps between readings.",
        },
      },
    ]);
    expect(screen.queryByRole("textbox", { name: "Name" })).not.toBeInTheDocument();
  });

  it("deletes the firmware after asking, and lands on the list without it", async () => {
    const writes = acceptFirmwareWrites([
      weatherStation,
      aFirmware({ id: "0199ffff-0000-7000-8000-000000000002", name: "Pico blink" }),
    ]);
    const router = renderAt(`/firmware/${FIRMWARE_ID}`, { answered: true });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete firmware" }));
    const question = screen.getByRole("group", {
      name: "Delete Weather station with all its versions and source files?",
    });
    await user.click(within(question).getByRole("button", { name: "Yes, delete it" }));

    expect(await screen.findByRole("heading", { name: "Firmware", level: 1 })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/firmware");
    expect(await screen.findByRole("link", { name: "Pico blink" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Weather station" })).not.toBeInTheDocument();
    expect(writes.deletions).toEqual([FIRMWARE_ID]);
  });

  it("keeps the firmware when the question is answered no", async () => {
    const writes = acceptFirmwareWrites([weatherStation]);
    renderAt(`/firmware/${FIRMWARE_ID}`, { answered: true });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete firmware" }));
    await user.click(screen.getByRole("button", { name: "Keep it" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Delete firmware" })).toBeInTheDocument(),
    );
    expect(writes.deletions).toEqual([]);
  });
});
