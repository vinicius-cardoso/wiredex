import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  FIRMWARE_ID,
  renderFirmwareAt,
  V100,
  V120,
  v100,
  v110,
  v120,
  weatherStationWith,
} from "../../test/firmware";
import { acceptFirmwareWrites, NEW_VERSION_ID } from "../../test/server";

function acceptWrites() {
  return acceptFirmwareWrites([weatherStationWith([v120, v110, v100])], {
    versions: [v120, v110, v100],
  });
}

describe("NewVersionDialog", () => {
  it("offers the suggested number and the highest version, and opens the new draft", async () => {
    const writes = acceptWrites();
    const router = renderFirmwareAt(`/firmware/${FIRMWARE_ID}`);
    const user = userEvent.setup();

    await screen.findByRole("region", { name: "Version 1.2.0" });
    await user.click(screen.getByRole("button", { name: "New version" }));
    const dialog = screen.getByRole("dialog", { name: "New version of Weather station" });
    expect(within(dialog).getByRole("textbox", { name: "Version number" })).toHaveValue("1.2.1");
    const from = within(dialog).getByRole("combobox", { name: "Start from" });
    expect(from).toHaveValue(V120);
    expect(
      within(from)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["1.2.0 · Draft", "1.1.0 · Released", "1.0.0 · Released", "An empty version"]);
    await user.click(within(dialog).getByRole("button", { name: "Start version" }));

    const panel = await screen.findByRole("region", { name: "Version 1.2.1" });
    expect(router.state.location.pathname).toBe(
      `/firmware/${FIRMWARE_ID}/versions/${NEW_VERSION_ID}`,
    );
    expect(await within(panel).findByRole("link", { name: "1.2.0" })).toBeInTheDocument();
    const files = within(panel).getByRole("navigation", { name: "Files in this version" });
    expect(within(files).getByRole("link", { name: /^config\.h/ })).toBeInTheDocument();
    const versions = screen.getByRole("navigation", { name: "Versions" });
    expect(within(versions).getByRole("link", { name: "1.2.1 · Draft" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(writes.versionStarts).toEqual([
      { firmwareId: FIRMWARE_ID, body: { version: "1.2.1", from_version_id: V120 } },
    ]);
  });

  it("starts from the version it was opened from, or from nothing", async () => {
    const writes = acceptWrites();
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}/versions/${V100}`);
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Version 1.0.0" });
    await user.click(await within(panel).findByRole("button", { name: "New version from this" }));
    const dialog = screen.getByRole("dialog", { name: "New version of Weather station" });
    const from = within(dialog).getByRole("combobox", { name: "Start from" });
    expect(from).toHaveValue(V100);
    await user.selectOptions(from, "An empty version");
    await user.click(within(dialog).getByRole("button", { name: "Start version" }));

    const started = await screen.findByRole("region", { name: "Version 1.2.1" });
    expect(await within(started).findByText("No source files yet.")).toBeInTheDocument();
    expect(writes.versionStarts).toEqual([
      { firmwareId: FIRMWARE_ID, body: { version: "1.2.1", from_version_id: null } },
    ]);
  });

  it("marks a number another version holds on the number field", async () => {
    acceptWrites();
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}`);
    const user = userEvent.setup();

    await screen.findByRole("region", { name: "Version 1.2.0" });
    await user.click(screen.getByRole("button", { name: "New version" }));
    const dialog = screen.getByRole("dialog", { name: "New version of Weather station" });
    const number = within(dialog).getByRole("textbox", { name: "Version number" });
    await user.clear(number);
    await user.type(number, "1.1.0");
    await user.click(within(dialog).getByRole("button", { name: "Start version" }));

    await waitFor(() => expect(number).toHaveAttribute("aria-invalid", "true"));
    expect(number).toHaveAccessibleDescription(
      expect.stringContaining("This firmware already has a version 1.1.0."),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("refuses a number that isn't SemVer before sending anything", async () => {
    const writes = acceptWrites();
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}`);
    const user = userEvent.setup();

    await screen.findByRole("region", { name: "Version 1.2.0" });
    await user.click(screen.getByRole("button", { name: "New version" }));
    const dialog = screen.getByRole("dialog", { name: "New version of Weather station" });
    const number = within(dialog).getByRole("textbox", { name: "Version number" });
    await user.clear(number);
    await user.type(number, "1.2+build.7");
    await user.click(within(dialog).getByRole("button", { name: "Start version" }));

    expect(number).toHaveAttribute("aria-invalid", "true");
    expect(number).toHaveAccessibleDescription(expect.stringContaining("Use MAJOR.MINOR.PATCH"));
    expect(writes.versionStarts).toEqual([]);
  });
});

describe("EditVersionDialog", () => {
  it("marks a number another version holds, and keeps the dialog open", async () => {
    const writes = acceptWrites();
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}`);
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Version 1.2.0" });
    await user.click(await within(panel).findByRole("button", { name: "Edit version" }));
    const dialog = screen.getByRole("dialog", { name: "Edit version 1.2.0" });
    const number = within(dialog).getByRole("textbox", { name: "Version number" });
    await user.clear(number);
    await user.type(number, "1.0.0");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(number).toHaveAccessibleDescription(
        expect.stringContaining("This firmware already has a version 1.0.0."),
      ),
    );
    expect(writes.versionEdits).toHaveLength(1);
  });
});
