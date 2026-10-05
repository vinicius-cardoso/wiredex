import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { FIRMWARE_ID, V100, V120, v100, v110, v120, weatherStationWith } from "../../test/firmware";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  acceptFirmwareWrites,
  aFirmware,
  respondAsLoggedIn,
  respondWithApiVersion,
  respondWithFirmware,
  respondWithVersion,
} from "../../test/server";

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

  it("lays the firmware out in blocks: About with what it runs on, Versions, Boards, the version, History", async () => {
    respondWithFirmware({
      ...weatherStationWith([v120, v110, v100]),
      runs_on: weatherStation.runs_on,
    });
    respondWithVersion(v120, v110, v100);
    renderAt(`/firmware/${FIRMWARE_ID}`, { answered: true });

    const about = await screen.findByRole("region", { name: "About" });
    expect(within(about).getByText("esp32:esp32:esp32")).toBeInTheDocument();
    expect(within(about).getByText("Arduino")).toBeInTheDocument();
    expect(within(about).getByRole("button", { name: "Edit firmware" })).toBeInTheDocument();
    expect(within(about).getByRole("button", { name: "Move to trash" })).toBeInTheDocument();
    // What it runs on is a part of About, under a heading of its own.
    const runsOn = within(about).getByRole("region", { name: "Runs on" });
    expect(within(runsOn).getByRole("heading", { level: 3 })).toHaveTextContent("Runs on");
    expect(within(runsOn).getAllByRole("link")).toHaveLength(2);
    expect(screen.getByRole("heading", { name: "About", level: 2 })).toBeInTheDocument();

    const versions = screen.getByRole("navigation", { name: "Versions" });
    expect(within(versions).getByRole("heading", { level: 2 })).toHaveTextContent("Versions");
    expect(about).not.toContainElement(versions);
    expect(screen.getByRole("region", { name: "Boards" })).toBeInTheDocument();
    // The open version and the history take the whole width of the page's grid.
    const panel = await screen.findByRole("region", { name: "Version 1.2.0" });
    expect(panel).toHaveClass("col-span-full");
    expect(screen.getByRole("region", { name: "History" })).toHaveClass("col-span-full");
    expect(screen.getByRole("region", { name: "Boards" })).toHaveClass(
      "xl:col-span-2",
      "2xl:col-span-1",
    );
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
    // The form takes the facts' place only: what it runs on stays in view, below it.
    const about = screen.getByRole("region", { name: "About" });
    expect(within(about).getByRole("textbox", { name: "Name" })).toBeInTheDocument();
    expect(within(about).getByRole("region", { name: "Runs on" })).toBeInTheDocument();
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

    await user.click(await screen.findByRole("button", { name: "Move to trash" }));
    const question = screen.getByRole("group", {
      name: "Move Weather station with all its versions and source files to the trash? You can restore it from there.",
    });
    await user.click(within(question).getByRole("button", { name: "Yes, move it" }));

    expect(await screen.findByRole("heading", { name: "Firmware", level: 1 })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/firmware");
    expect(await screen.findByRole("link", { name: "Pico blink" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Weather station" })).not.toBeInTheDocument();
    expect(writes.deletions).toEqual([FIRMWARE_ID]);
  });

  it("opens the highest version, links the others and marks the open one", async () => {
    respondWithFirmware(weatherStationWith([v120, v110, v100]));
    respondWithVersion(v120, v110, v100);
    const router = renderAt(`/firmware/${FIRMWARE_ID}`, { answered: true });
    const user = userEvent.setup();

    expect(await screen.findByRole("region", { name: "Version 1.2.0" })).toBeInTheDocument();
    const versions = screen.getByRole("navigation", { name: "Versions" });
    const links = within(versions).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "1.2.0 · Draft",
      "1.1.0 · Released",
      "1.0.0 · Released",
    ]);
    expect(links[0]).toHaveAttribute("aria-current", "page");
    expect(links[1]).not.toHaveAttribute("aria-current");
    expect(links[2]).toHaveAttribute("href", `/firmware/${FIRMWARE_ID}/versions/${V100}`);
    expect(within(versions).getByRole("button", { name: "New version" })).toBeInTheDocument();

    await user.click(within(versions).getByRole("link", { name: "1.0.0 · Released" }));

    expect(await screen.findByRole("region", { name: "Version 1.0.0" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(`/firmware/${FIRMWARE_ID}/versions/${V100}`);
    const marked = within(screen.getByRole("navigation", { name: "Versions" })).getByRole("link", {
      name: "1.0.0 · Released",
    });
    expect(marked).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("region", { name: "Version 1.2.0" })).not.toBeInTheDocument();
  });

  it("says so when the address names a version the firmware doesn't hold", async () => {
    respondWithFirmware(weatherStationWith([v120, v110, v100]));
    respondWithVersion(v120, v110, v100);
    renderAt(`/firmware/${FIRMWARE_ID}/versions/0199ffff-0000-7000-8000-0000000000ff`, {
      answered: true,
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This firmware has no such version.");
    expect(within(alert).getByRole("link", { name: "Open the highest, 1.2.0" })).toHaveAttribute(
      "href",
      `/firmware/${FIRMWARE_ID}/versions/${V120}`,
    );
  });

  it("offers a first version when there is none yet", async () => {
    renderAt(`/firmware/${FIRMWARE_ID}`);

    expect(
      await screen.findByText("No version yet. Start the first one, then add its source files."),
    ).toBeInTheDocument();
    const versions = screen.getByRole("navigation", { name: "Versions" });
    expect(within(versions).queryByRole("link")).not.toBeInTheDocument();
    expect(within(versions).getByRole("button", { name: "New version" })).toBeInTheDocument();
  });

  it("deletes a version after asking, and opens the firmware's highest", async () => {
    const writes = acceptFirmwareWrites([weatherStationWith([v120, v110, v100])], {
      versions: [v120, v110, v100],
    });
    const router = renderAt(`/firmware/${FIRMWARE_ID}/versions/${V100}`, { answered: true });
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Version 1.0.0" });
    await user.click(await within(panel).findByRole("button", { name: "Delete version" }));
    const question = within(panel).getByRole("group", {
      name: "Delete version 1.0.0 with its source files?",
    });
    await user.click(within(question).getByRole("button", { name: "Yes, delete it" }));

    expect(await screen.findByRole("region", { name: "Version 1.2.0" })).toBeInTheDocument();
    await waitFor(() => expect(router.state.location.pathname).toBe(`/firmware/${FIRMWARE_ID}`));
    const versions = screen.getByRole("navigation", { name: "Versions" });
    await waitFor(() =>
      expect(
        within(versions)
          .getAllByRole("link")
          .map((link) => link.textContent),
      ).toEqual(["1.2.0 · Draft", "1.1.0 · Released"]),
    );
    expect(writes.versionDeletions).toEqual([V100]);
  });

  it("keeps the firmware when the question is answered no", async () => {
    const writes = acceptFirmwareWrites([weatherStation]);
    renderAt(`/firmware/${FIRMWARE_ID}`, { answered: true });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Move to trash" }));
    await user.click(screen.getByRole("button", { name: "Keep it" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Move to trash" })).toBeInTheDocument(),
    );
    expect(writes.deletions).toEqual([]);
  });
});
