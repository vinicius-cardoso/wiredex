import { File as NodeFile } from "node:buffer";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  FIRMWARE_ID,
  renderFirmwareAt,
  V110,
  V120,
  v100,
  v110,
  v120,
  weatherStationWith,
} from "../../test/firmware";
import { renderWithProviders } from "../../test/render";
import {
  acceptFirmwareWrites,
  acceptUploads,
  anAttachment,
  refuseUploads,
  respondWithAttachments,
  respondWithBoards,
} from "../../test/server";
import { BuildsSection } from "./BuildsSection";
import { buildsSubject } from "./flashing/useStoredBuild";

const station = weatherStationWith([v120, v110, v100]);
const subject = buildsSubject(V110);

const aBuild = (id: string, title: string, createdAt: string) =>
  anAttachment({
    id,
    subject,
    kind: "firmware_build",
    title,
    media_type: "application/zip",
    size: 174_352,
    created_at: createdAt,
  });

const newer = aBuild(
  "0199eeee-0000-7000-8000-0000000000b2",
  "Build 2026-10-09 21:40 UTC · arduino-cli 1.4.1",
  "2026-10-09T21:40:05Z",
);
const older = aBuild(
  "0199eeee-0000-7000-8000-0000000000b1",
  "Build 2026-10-02 08:15 UTC · arduino-cli 1.3.0",
  "2026-10-02T08:15:00Z",
);

// jsdom's File hides its bytes from the request serializer, as DropZone's tests found: Node's
// own is what a browser hands the input anyway.
function aFile(name: string, type: string, bytes: string): File {
  return new NodeFile([bytes], name, { type }) as unknown as File;
}

function renderBuilds(builds = [newer, older]) {
  respondWithAttachments(subject, builds);
  renderWithProviders(<BuildsSection firmware={station} version={v110} />);
  return screen.getByRole("region", { name: "Builds" });
}

describe("BuildsSection", () => {
  it("lists a version's builds newest first, each to download or remove", async () => {
    const user = userEvent.setup();
    const region = renderBuilds();

    const rows = await within(region).findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    // The newest is the one the flash dialog writes, and says so.
    expect(rows[0]).toHaveTextContent("Build 2026-10-09 21:40 UTC · arduino-cli 1.4.1Newest");
    expect(rows[0]).toHaveTextContent("170.3 KB");
    expect(rows[1]).not.toHaveTextContent("Newest");
    const download = within(rows[1] as HTMLElement).getByRole("link", {
      name: "Download Build 2026-10-02 08:15 UTC · arduino-cli 1.3.0",
    });
    expect(download).toHaveAttribute("href", older.content_url);
    expect(download).toHaveAttribute("download");

    await user.click(
      within(rows[1] as HTMLElement).getByRole("button", { name: /^Remove Build 2026-10-02/ }),
    );
    await user.click(within(region).getByRole("button", { name: "Remove attachment" }));
    await waitFor(() => expect(within(region).getAllByRole("listitem")).toHaveLength(1));
  });

  it("shows the command that makes a build when the version has none", async () => {
    const region = renderBuilds([]);

    expect(
      await within(region).findByText(
        "No build is stored for this version yet. On a computer with arduino-cli, run:",
      ),
    ).toBeInTheDocument();
    // The name in quotes, since it holds a space a shell would split on.
    expect(
      within(region).getByText('wiredex firmware build "Weather station" 1.1.0'),
    ).toBeInTheDocument();
  });

  it("stores a zip added from the computer as a build of the version", async () => {
    const user = userEvent.setup();
    const sent = acceptUploads(newer);
    const region = renderBuilds([]);
    const zip = aFile("build.zip", "application/zip", "PK\x03\x04");

    await user.upload(await within(region).findByLabelText("Add a build's zip"), zip);

    expect(await within(region).findByText("The build is stored.")).toBeInTheDocument();
    expect(sent).toEqual([{ subject, kind: "firmware_build", title: null, hasFile: true }]);
  });

  it("says what a build is when the file isn't one", async () => {
    const user = userEvent.setup({ applyAccept: false });
    refuseUploads("a firmware version takes a build: a ZIP of its binaries", 415);
    const region = renderBuilds([]);

    await user.upload(
      await within(region).findByLabelText("Add a build's zip"),
      aFile("notes.pdf", "application/pdf", "%PDF-notes"),
    );

    expect(await within(region).findByRole("alert")).toHaveTextContent(
      "A build is a zip of the binaries with their manifest.",
    );
  });

  it("is on a released version's panel and not on a draft's", async () => {
    acceptFirmwareWrites([station], { versions: [v120, v110, v100] });
    respondWithBoards(FIRMWARE_ID, () => []);
    respondWithAttachments(subject, [newer]);
    const router = renderFirmwareAt(`/firmware/${FIRMWARE_ID}/versions/${V110}`);

    const released = await screen.findByRole("region", { name: "Version 1.1.0" });
    expect(await within(released).findByRole("region", { name: "Builds" })).toBeInTheDocument();

    await router.navigate({
      to: "/firmware/$firmwareId/versions/$versionId",
      params: { firmwareId: FIRMWARE_ID, versionId: V120 },
    });
    const draft = await screen.findByRole("region", { name: "Version 1.2.0" });
    await within(draft).findByRole("button", { name: "New version from this" });
    expect(within(draft).queryByRole("region", { name: "Builds" })).not.toBeInTheDocument();
  });
});
