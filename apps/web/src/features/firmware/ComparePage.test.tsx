import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  blink,
  FIRMWARE_ID,
  renderFirmwareAt,
  V100,
  V110,
  V120,
  v100,
  v110,
  v120,
  weatherStationWith,
} from "../../test/firmware";
import { aVersion, respondWithFirmware, respondWithVersion } from "../../test/server";

const compare = (search: string) => `/firmware/${FIRMWARE_ID}/compare${search}`;

describe("ComparePage", () => {
  it("compares the two versions the address names", async () => {
    const released = aVersion({
      id: V100,
      version: "1.0.0",
      status: "released",
      files: [blink.sketch, blink.header, blink.notes],
    });
    const draft = aVersion({
      id: V110,
      version: "1.1.0",
      based_on: { id: V100, version: "1.0.0" },
      files: [blink.changed, blink.source, blink.notes],
    });
    respondWithFirmware(weatherStationWith([draft, released]));
    respondWithVersion(draft, released);
    renderFirmwareAt(compare(`?from=${V100}&to=${V110}`));

    expect(
      await screen.findByRole("heading", { name: "Compare versions", level: 1 }),
    ).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "← Weather station" })).toHaveAttribute(
      "href",
      `/firmware/${FIRMWARE_ID}`,
    );
    expect(screen.getByRole("combobox", { name: "From" })).toHaveDisplayValue("1.0.0 · Released");
    expect(screen.getByRole("combobox", { name: "To" })).toHaveDisplayValue("1.1.0 · Draft");
    const summary = await screen.findByRole("list", { name: "Summary" });
    expect(summary).toHaveTextContent("1 file changed");
    const changed = screen.getByRole("region", { name: "app.ino, changed" });
    expect(within(changed).getAllByText("added")).toHaveLength(3);
    expect(within(changed).getAllByText("removed")).toHaveLength(1);
  });

  it("keeps the chosen versions in the address, so Back walks them", async () => {
    respondWithFirmware(weatherStationWith([v120, v110, v100]));
    respondWithVersion(v120, v110, v100);
    const router = renderFirmwareAt(compare(`?from=${V100}&to=${V110}`));
    const user = userEvent.setup();

    expect(await screen.findByRole("region", { name: "config.h, added" })).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "From" }), "1.1.0 · Released");
    await user.selectOptions(screen.getByRole("combobox", { name: "To" }), "1.2.0 · Draft");

    expect(router.state.location.search).toEqual({ from: V110, to: V120 });
    expect(
      await screen.findByText("The two versions hold the same files, with the same text."),
    ).toBeInTheDocument();

    router.history.back();
    await waitFor(() => expect(router.state.location.search).toEqual({ from: V110, to: V110 }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Choose two different versions to compare.",
    );
    router.history.back();
    expect(await screen.findByRole("region", { name: "config.h, added" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "From" })).toHaveDisplayValue("1.0.0 · Released");
    expect(screen.getByRole("combobox", { name: "To" })).toHaveDisplayValue("1.1.0 · Released");
  });

  it("opens the highest version against its base when the address names none", async () => {
    respondWithFirmware(weatherStationWith([v120, v110, v100]));
    respondWithVersion(v120, v110, v100);
    renderFirmwareAt(compare(""));

    expect(await screen.findByRole("combobox", { name: "From" })).toHaveDisplayValue(
      "1.1.0 · Released",
    );
    expect(screen.getByRole("combobox", { name: "To" })).toHaveDisplayValue("1.2.0 · Draft");
    expect(
      await screen.findByText("The two versions hold the same files, with the same text."),
    ).toBeInTheDocument();
  });

  it("asks for two different versions when both sides name the same one", async () => {
    respondWithFirmware(weatherStationWith([v120, v110, v100]));
    respondWithVersion(v120, v110, v100);
    renderFirmwareAt(compare(`?from=${V110}&to=${V110}`));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Choose two different versions to compare.",
    );
    expect(screen.getByRole("combobox", { name: "From" })).toHaveDisplayValue("1.1.0 · Released");
    expect(screen.queryByRole("list", { name: "Summary" })).not.toBeInTheDocument();
  });

  it("says a version of another firmware isn't this one's, and offers the choice again", async () => {
    const elsewhere = aVersion({ id: "0199ffff-0000-7000-8000-0000000000d1", version: "1.0.0" });
    respondWithFirmware(weatherStationWith([v120, v110, v100]));
    respondWithVersion(v120, v110, v100, elsewhere);
    const router = renderFirmwareAt(compare(`?from=${elsewhere.id}&to=${V110}`));
    const user = userEvent.setup();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This firmware has no such version. Choose one of its versions instead.",
    );
    const from = screen.getByRole("combobox", { name: "From" });
    expect(from).toHaveDisplayValue("Choose a version");

    await user.selectOptions(from, "1.0.0 · Released");
    expect(router.state.location.search).toEqual({ from: V100, to: V110 });
    expect(await screen.findByRole("region", { name: "config.h, added" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says a version the firmware lists but that has gone isn't this one's", async () => {
    respondWithFirmware(weatherStationWith([v110, v100]));
    respondWithVersion(v110);
    renderFirmwareAt(compare(`?from=${V100}&to=${V110}`));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This firmware has no such version. Choose one of its versions instead.",
    );
  });

  it("says a firmware with a single version has nothing to compare it with", async () => {
    respondWithFirmware(weatherStationWith([v100]));
    respondWithVersion(v100);
    renderFirmwareAt(compare(""));

    expect(
      await screen.findByText("A comparison needs two versions, and this firmware has fewer."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "From" })).not.toBeInTheDocument();
  });
});
