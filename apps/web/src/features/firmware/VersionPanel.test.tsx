import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  codeOf,
  FIRMWARE_ID,
  renderFirmwareAt,
  sketch,
  V110,
  V120,
  v100,
  v110,
  v120,
  weatherStationWith,
} from "../../test/firmware";
import { acceptFirmwareWrites, respondWithFirmware, respondWithVersion } from "../../test/server";

describe("VersionPanel", () => {
  it("shows a draft's base and changelog, and offers every action", async () => {
    respondWithFirmware(weatherStationWith([v120, v110, v100]));
    respondWithVersion(v120, v110, v100);
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}`);

    const panel = await screen.findByRole("region", { name: "Version 1.2.0" });
    expect(within(panel).getByText("Draft")).toBeInTheDocument();
    expect(await within(panel).findByRole("link", { name: "1.1.0" })).toHaveAttribute(
      "href",
      `/firmware/${FIRMWARE_ID}/versions/${V110}`,
    );
    expect(within(panel).getByText("Averages three readings.")).toBeInTheDocument();
    expect(within(panel).queryByText("Released on")).not.toBeInTheDocument();
    const actions = ["Edit version", "Release", "New version from this", "Delete version"];
    for (const name of actions) {
      expect(within(panel).getByRole("button", { name })).toBeInTheDocument();
    }
    expect(within(panel).getByRole("button", { name: "Release" })).not.toHaveAttribute(
      "aria-disabled",
    );
  });

  it("shows a release with its date, and offers no edit and no release", async () => {
    respondWithFirmware(weatherStationWith([v120, v110, v100]));
    respondWithVersion(v120, v110, v100);
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}/versions/${V110}`);

    const panel = await screen.findByRole("region", { name: "Version 1.1.0" });
    expect(within(panel).getByText("Released")).toBeInTheDocument();
    expect(await within(panel).findByText("Released on")).toBeInTheDocument();
    expect(within(panel).getByText("Sep 29, 2026")).toHaveAttribute(
      "datetime",
      "2026-09-29T10:00:00Z",
    );
    // The changelog keeps its line break.
    expect(within(panel).getByText(/Sleeps between readings/)).toHaveTextContent(
      "Sleeps between readings. Moves the pins into config.h.",
    );
    expect(within(panel).getByRole("button", { name: "New version from this" })).toBeVisible();
    expect(within(panel).getByRole("button", { name: "Delete version" })).toBeVisible();
    expect(within(panel).queryByRole("button", { name: "Edit version" })).not.toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Release" })).not.toBeInTheDocument();
  });

  it.each([
    [
      "no file",
      { files: [], changelog: "Averages three readings." },
      "Add a source file before releasing.",
    ],
    [
      "no file and no changelog",
      { files: [], changelog: null },
      "Add a source file and write a changelog before releasing.",
    ],
  ])("keeps Release unavailable for a draft with %s, saying why", async (_, change, reason) => {
    const draft = { ...v120, ...change, size: 0 };
    respondWithFirmware(weatherStationWith([draft, v110, v100]));
    respondWithVersion(draft, v110, v100);
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}`);
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Version 1.2.0" });
    const release = await within(panel).findByRole("button", { name: "Release" });
    expect(release).toHaveAttribute("aria-disabled", "true");
    expect(release).toHaveAccessibleDescription(reason);
    await user.click(release);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("asks for a changelog before releasing, then asks first and releases", async () => {
    const draft = { ...v120, changelog: null };
    const writes = acceptFirmwareWrites([weatherStationWith([draft, v110, v100])], {
      versions: [draft, v110, v100],
    });
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}`);
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Version 1.2.0" });
    const unavailable = await within(panel).findByRole("button", { name: "Release" });
    expect(unavailable).toHaveAccessibleDescription("Write a changelog before releasing.");

    await user.click(within(panel).getByRole("button", { name: "Edit version" }));
    const edit = screen.getByRole("dialog", { name: "Edit version 1.2.0" });
    expect(within(edit).getByRole("textbox", { name: "Version number" })).toHaveValue("1.2.0");
    await user.type(within(edit).getByRole("textbox", { name: "Changelog" }), "Averages three.");
    await user.click(within(edit).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const opened = await screen.findByRole("region", { name: "Version 1.2.0" });
    expect(await within(opened).findByText("Averages three.")).toBeInTheDocument();
    const release = within(opened).getByRole("button", { name: "Release" });
    expect(release).not.toHaveAttribute("aria-disabled");

    await user.click(release);
    const question = screen.getByRole("dialog", { name: "Release version 1.2.0?" });
    expect(question).toHaveTextContent(
      "Once released, its files and changelog won't change again. A change will need a new version.",
    );
    await user.click(within(question).getByRole("button", { name: "Release 1.2.0" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const released = screen.getByRole("region", { name: "Version 1.2.0" });
    expect(await within(released).findByText("Released on")).toBeInTheDocument();
    expect(within(released).queryByRole("button", { name: "Edit version" })).toBeNull();
    expect(within(released).queryByRole("button", { name: "Release" })).toBeNull();
    const versions = screen.getByRole("navigation", { name: "Versions" });
    expect(within(versions).getByRole("link", { name: "1.2.0 · Released" })).toBeInTheDocument();
    expect(writes.versionEdits).toEqual([
      { versionId: V120, body: { version: "1.2.0", changelog: "Averages three." } },
    ]);
    expect(writes.releases).toEqual([V120]);
  });

  it("offers Compare with the version's base, and nothing on a first version", async () => {
    respondWithFirmware(weatherStationWith([v120, v110, v100]));
    respondWithVersion(v120, v110, v100);
    const router = renderFirmwareAt(`/firmware/${FIRMWARE_ID}/versions/${V120}`);
    const user = userEvent.setup();

    const draft = await screen.findByRole("region", { name: "Version 1.2.0" });
    const compare = await within(draft).findByRole("link", { name: "Compare with 1.1.0" });
    expect(compare).toHaveAttribute(
      "href",
      `/firmware/${FIRMWARE_ID}/compare?from=${V110}&to=${V120}`,
    );

    await user.click(screen.getByRole("link", { name: "1.0.0 · Released" }));
    const first = await screen.findByRole("region", { name: "Version 1.0.0" });
    expect(await within(first).findByText("Released on")).toBeInTheDocument();
    expect(within(first).queryByRole("link", { name: /^Compare with/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "1.2.0 · Draft" }));
    await user.click(await screen.findByRole("link", { name: "Compare with 1.1.0" }));
    expect(
      await screen.findByRole("heading", { name: "Compare versions", level: 1 }),
    ).toBeInTheDocument();
    expect(router.state.location.search).toEqual({ from: V110, to: V120 });
  });

  it("shows each file's text in the version's files", async () => {
    respondWithFirmware(weatherStationWith([v120, v110, v100]));
    respondWithVersion(v120, v110, v100);
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}/versions/${V120}`);

    const file = await screen.findByRole("region", { name: "weather_station.ino" });
    expect(codeOf(within(file).getByRole("group", { name: "weather_station.ino" }))).toBe(
      sketch.content,
    );
  });
});
