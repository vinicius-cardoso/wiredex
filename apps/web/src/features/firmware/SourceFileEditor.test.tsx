import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  codeOf,
  config,
  FIRMWARE_ID,
  renderFirmwareAt,
  sketch,
  V120,
  weatherStationWith,
} from "../../test/firmware";
import { acceptFirmwareWrites, aVersion } from "../../test/server";

/** The weather station's draft, holding FILES, as the only version its page lists. */
function draftWith(files = [sketch, config]) {
  const draft = aVersion({ id: V120, version: "1.2.0", files });
  const writes = acceptFirmwareWrites([weatherStationWith([draft])], { versions: [draft] });
  renderFirmwareAt(`/firmware/${FIRMWARE_ID}`);
  return writes;
}

describe("SourceFileEditor", () => {
  it("sends a typed file as typed, tabs and trailing spaces kept, and shows it", async () => {
    const user = userEvent.setup();
    const writes = draftWith([]);
    const panel = await screen.findByRole("region", { name: "Version 1.2.0" });
    await user.click(await within(panel).findByRole("button", { name: "Add a file" }));

    const editor = within(panel).getByRole("form", { name: "New file" });
    const path = within(editor).getByRole("textbox", { name: "Path" });
    expect(path).toHaveFocus();
    // An Arduino firmware's first file is offered the sketch's name.
    expect(path).toHaveAttribute("placeholder", "sketch.ino");
    await user.type(path, "blink.ino");
    const text = "void setup() {\n\tpinMode(LED_BUILTIN, OUTPUT);  \n}\n\nvoid loop() {}";
    await user.click(within(editor).getByRole("textbox", { name: "Code" }));
    await user.paste(text);
    await user.click(within(editor).getByRole("button", { name: "Add file" }));

    await waitFor(() => expect(writes.fileAdds).toHaveLength(1));
    expect(writes.fileAdds[0]).toEqual({
      versionId: V120,
      body: { files: [{ path: "blink.ino", content: text }] },
    });
    const file = await within(panel).findByRole("region", { name: "blink.ino" });
    expect(codeOf(within(file).getByRole("group", { name: "blink.ino" }))).toBe(text);
    expect(within(panel).queryByRole("form", { name: "New file" })).not.toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Add a file" })).toHaveFocus();
  });

  it("moves the focus on when Tab is pressed in the text box, typing no tab", async () => {
    const user = userEvent.setup();
    draftWith();
    const panel = await screen.findByRole("region", { name: "Version 1.2.0" });
    await user.click(await within(panel).findByRole("button", { name: "Add a file" }));
    const editor = within(panel).getByRole("form", { name: "New file" });
    const text = within(editor).getByRole("textbox", { name: "Code" });
    // A later file is offered no name: the sketch is already there.
    expect(within(editor).getByRole("textbox", { name: "Path" })).not.toHaveAttribute(
      "placeholder",
    );

    await user.click(text);
    await user.paste("int x;");
    await user.tab();

    expect(text).toHaveValue("int x;");
    expect(within(editor).getByRole("button", { name: "Add file" })).toHaveFocus();
  });

  it("renames a file under its id, and marks a path another file holds on the path", async () => {
    const user = userEvent.setup();
    const writes = draftWith();
    const panel = await screen.findByRole("region", { name: "Version 1.2.0" });
    await user.click(await within(panel).findByRole("button", { name: "Edit config.h" }));

    const editor = within(panel).getByRole("form", { name: "Editing config.h" });
    const path = within(editor).getByRole("textbox", { name: "Path" });
    expect(within(editor).getByRole("textbox", { name: "Code" })).toHaveValue(config.content);
    await user.clear(path);
    await user.type(path, "Weather_Station.ino");
    await user.click(within(editor).getByRole("button", { name: "Save file" }));

    // The fake answers the API's 409 `path_taken` on the path, as typed.
    await waitFor(() => expect(path).toHaveAttribute("aria-invalid", "true"));
    expect(path).toHaveAccessibleDescription(
      expect.stringContaining("Weather_Station.ino clashes with another file of this version"),
    );
    expect(path).toHaveFocus();

    await user.clear(path);
    await user.type(path, "include/config.h");
    expect(path).not.toHaveAttribute("aria-invalid");
    await user.click(within(editor).getByRole("button", { name: "Save file" }));

    await waitFor(() => expect(writes.fileEdits).toHaveLength(2));
    expect(writes.fileEdits[1]).toEqual({
      versionId: V120,
      fileId: config.id,
      body: { path: "include/config.h", content: config.content },
    });
    const edit = await within(panel).findByRole("button", { name: "Edit include/config.h" });
    expect(edit).toHaveFocus();
    expect(within(panel).queryByRole("form")).not.toBeInTheDocument();
  });
});
