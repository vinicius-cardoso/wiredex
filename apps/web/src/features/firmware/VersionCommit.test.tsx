import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  FIRMWARE_ID,
  renderFirmwareAt,
  V110,
  v100,
  v110,
  v120,
  weatherStationWith,
} from "../../test/firmware";
import { acceptFirmwareWrites } from "../../test/server";

const SHA = "9fceb02d0ae598e95dc970b74767f19372d61af8";
const REPOSITORY = "https://github.com/me/station";

describe("a version's commit", () => {
  it("links a commit to a released version, and opens it in the repository", async () => {
    const station = { ...weatherStationWith([v120, v110, v100]), repository: REPOSITORY };
    const writes = acceptFirmwareWrites([station], { versions: [v120, v110, v100] });
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}/versions/${V110}`);
    const user = userEvent.setup();

    expect(await screen.findByRole("link", { name: "github.com/me/station" })).toHaveAttribute(
      "href",
      REPOSITORY,
    );
    const panel = await screen.findByRole("region", { name: "Version 1.1.0" });
    expect(await within(panel).findByText("No commit linked.")).toBeInTheDocument();

    await user.click(within(panel).getByRole("button", { name: "Link a commit" }));
    const field = within(panel).getByRole("textbox", { name: "Commit of version 1.1.0" });
    expect(field).toHaveFocus();
    await user.type(field, `${SHA}{Enter}`);

    expect(await within(panel).findByRole("link", { name: "9fceb02" })).toHaveAttribute(
      "href",
      `${REPOSITORY}/commit/${SHA}`,
    );
    expect(writes.commits).toEqual([{ versionId: V110, commit: SHA }]);
    expect(within(panel).queryByRole("textbox", { name: /^Commit of/ })).not.toBeInTheDocument();
  });

  it("shows a commit as text when the firmware has no repository, and clears it", async () => {
    const linked = { ...v120, commit: SHA };
    const writes = acceptFirmwareWrites([weatherStationWith([linked, v110, v100])], {
      versions: [linked, v110, v100],
    });
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}`);
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Version 1.2.0" });
    expect(await within(panel).findByText("9fceb02")).toBeInTheDocument();
    expect(within(panel).queryByRole("link", { name: "9fceb02" })).not.toBeInTheDocument();

    await user.click(within(panel).getByRole("button", { name: "Change" }));
    const field = within(panel).getByRole("textbox", { name: "Commit of version 1.2.0" });
    expect(field).toHaveValue(SHA);
    await user.clear(field);
    await user.click(within(panel).getByRole("button", { name: "Save" }));

    expect(await within(panel).findByText("No commit linked.")).toBeInTheDocument();
    expect(writes.commits).toEqual([{ versionId: linked.id, commit: null }]);
  });

  it("says why a branch name isn't a commit, and keeps what was typed", async () => {
    acceptFirmwareWrites([weatherStationWith([v120, v110, v100])], {
      versions: [v120, v110, v100],
    });
    renderFirmwareAt(`/firmware/${FIRMWARE_ID}`);
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Version 1.2.0" });
    await user.click(await within(panel).findByRole("button", { name: "Link a commit" }));
    const field = within(panel).getByRole("textbox", { name: "Commit of version 1.2.0" });
    await user.type(field, "main{Enter}");

    expect(await within(panel).findByRole("alert")).toHaveTextContent(
      /This isn't a commit: use the 7 to 64 digits/,
    );
    expect(field).toHaveValue("main");

    await user.click(within(panel).getByRole("button", { name: "Cancel" }));
    expect(within(panel).getByText("No commit linked.")).toBeInTheDocument();
  });
});
