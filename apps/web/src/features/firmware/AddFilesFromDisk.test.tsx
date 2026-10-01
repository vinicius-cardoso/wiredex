import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { sketch, V120, weatherStationWith } from "../../test/firmware";
import { renderWithProviders } from "../../test/render";
import { acceptFirmwareWrites, aVersion } from "../../test/server";
import { AddFilesFromDisk } from "./AddFilesFromDisk";

function renderDraft(overrides: Parameters<typeof aVersion>[0] = {}) {
  const draft = aVersion({ id: V120, version: "1.2.0", files: [sketch], ...overrides });
  const writes = acceptFirmwareWrites([weatherStationWith([draft])], { versions: [draft] });
  renderWithProviders(<AddFilesFromDisk version={draft} />);
  return writes;
}

describe("AddFilesFromDisk", () => {
  it("adds the files chosen in one request, each named by its file name", async () => {
    const user = userEvent.setup();
    const writes = renderDraft();
    const chosen = [
      new File(["#define SDA_PIN 21\r\n#define SCL_PIN 22\r\n"], "config.h"),
      new File(['#include "sensor.h"\n\nfloat read() {\n\treturn 0;\n}\n'], "sensor.cpp"),
      new File(["float read();"], "sensor.h"),
    ];

    await user.upload(screen.getByLabelText("Add files from the computer"), chosen);

    await waitFor(() => expect(writes.fileAdds).toHaveLength(1));
    // Sent as read; the server reads CRLF as LF.
    expect(writes.fileAdds[0]).toEqual({
      versionId: V120,
      body: {
        files: [
          { path: "config.h", content: "#define SDA_PIN 21\r\n#define SCL_PIN 22\r\n" },
          {
            path: "sensor.cpp",
            content: '#include "sensor.h"\n\nfloat read() {\n\treturn 0;\n}\n',
          },
          { path: "sensor.h", content: "float read();" },
        ],
      },
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Added 3 files.");
  });

  it("refuses a file that isn't text before sending anything", async () => {
    const user = userEvent.setup();
    const writes = renderDraft();
    const binary = new File([new Uint8Array([0x7f, 0x45, 0x4c, 0x46, 0x00, 0x01])], "blink.bin");

    await user.upload(screen.getByLabelText("Add files from the computer"), [
      new File(["float read();"], "sensor.h"),
      binary,
    ]);

    expect(await screen.findByRole("alert")).toHaveTextContent("blink.bin isn't text");
    expect(writes.fileAdds).toHaveLength(0);
  });

  it("refuses files that would pass the room left before sending anything", async () => {
    const user = userEvent.setup();
    // Ten bytes left; the two files take twenty.
    const writes = renderDraft({ size: 1_048_566 });

    await user.upload(screen.getByLabelText("Add files from the computer"), [
      new File(["0123456789"], "a.h"),
      new File(["0123456789"], "b.h"),
    ]);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "These files take 20 B and the version has 10 B left, so nothing was added.",
    );
    expect(writes.fileAdds).toHaveLength(0);
  });
});
