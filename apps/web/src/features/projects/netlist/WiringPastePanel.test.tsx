import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderInRouter } from "../../../test/render";
import {
  acceptNetWrites,
  aNet,
  aNetlist,
  aRevision,
  respondWithNetlist,
} from "../../../test/server";
import { NetlistSection } from "./NetlistSection";

const REVISION = aRevision();

async function openPaste(refuse: Parameters<typeof acceptNetWrites>[2] = null) {
  const writes = acceptNetWrites(REVISION.id, aNetlist({ nets: [aNet()] }), refuse);
  renderInRouter(<NetlistSection revision={REVISION} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Paste a table" }));
  const panel = screen.getByRole("region", { name: "Paste the wiring" });
  return {
    writes,
    panel,
    user,
    text: within(panel).getByRole("textbox", { name: "Pasted table" }),
  };
}

describe("pasting wiring", () => {
  it("shows the lines as read, then adds them all at once", async () => {
    const { writes, panel, user, text } = await openPaste();
    const add = within(panel).getByRole("button", { name: "Add to the wiring" });
    expect(add).toBeDisabled();

    await user.click(text);
    await user.paste("SCL; U1.22, U2.4; yellow\nU1.4, R1.1");

    const preview = within(panel).getByRole("table", { name: "Pasted wiring" });
    expect(within(preview).getByRole("row", { name: /SCL Yellow U1\.22, U2\.4/ })).toBeVisible();
    expect(within(preview).getByRole("row", { name: /Named after its pins/ })).toBeVisible();

    await user.click(add);

    expect(await screen.findByRole("row", { name: /^SCL/ })).toBeInTheDocument();
    expect(writes.pastes).toEqual([
      [
        { pins: "U1.22, U2.4", name: "SCL", color: "yellow", notes: null },
        { pins: "U1.4, R1.1", name: null, color: null, notes: null },
      ],
    ]);
    expect(screen.queryByRole("region", { name: "Paste the wiring" })).not.toBeInTheDocument();
  });

  it("sends the connections between two parts as pairs of pins", async () => {
    const { writes, panel, user, text } = await openPaste();

    await user.click(text);
    await user.paste("U1; U2\n25; SDA\n22; SCL");
    expect(within(panel).getByText(/Read as the connections between U1 and U2\./)).toBeVisible();
    await user.click(within(panel).getByRole("button", { name: "Add to the wiring" }));

    await screen.findByRole("button", { name: "Paste a table" });
    expect(writes.pastes[0]?.map((row) => row.pins)).toEqual(["U1.25, U2.SDA", "U1.22, U2.SCL"]);
  });

  it("holds back a paste with a line it couldn't read", async () => {
    const { panel, user, text } = await openPaste();

    await user.click(text);
    await user.paste("SDA; U1.25, U2.3\nSCL; yellow");

    expect(within(panel).getByText(/No pin found on this line/)).toBeVisible();
    expect(within(panel).getByText(/Fix or remove the lines marked above/)).toBeVisible();
    expect(within(panel).getByRole("button", { name: "Add to the wiring" })).toBeDisabled();
  });

  it("says which pasted line was refused, and keeps the text", async () => {
    const { writes, panel, user, text } = await openPaste({
      status: 422,
      body: { code: "unknown_pin", field: "pins", item: "U2.99", row: 2 },
    });

    await user.click(text);
    await user.paste("Net; Pins\nSDA; U1.25, U2.3\nSCL; U1.22, U2.99");
    await user.click(within(panel).getByRole("button", { name: "Add to the wiring" }));

    expect(await within(panel).findByRole("alert")).toHaveTextContent(
      "Line 3: U2.99: that part has no such pin. Nothing was added. Fix that line and try again.",
    );
    expect(writes.pastes).toEqual([]);
    expect(text).toHaveValue("Net; Pins\nSDA; U1.25, U2.3\nSCL; U1.22, U2.99");
  });

  it("closes without adding anything", async () => {
    const { writes, panel, user } = await openPaste();

    await user.click(within(panel).getByRole("button", { name: "Cancel the paste" }));

    expect(screen.queryByRole("region", { name: "Paste the wiring" })).not.toBeInTheDocument();
    expect(writes.pastes).toEqual([]);
  });

  it("isn't offered where the wiring can't change", async () => {
    respondWithNetlist(REVISION.id, aNetlist({ nets: [aNet()], editable: false }));
    renderInRouter(<NetlistSection revision={REVISION} />);

    await screen.findByRole("row", { name: /^SDA/ });
    expect(screen.queryByRole("button", { name: "Paste a table" })).not.toBeInTheDocument();
  });
});
