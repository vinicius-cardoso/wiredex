import { File as NodeFile } from "node:buffer";
import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "../../test/render";
import { acceptUploads, refuseUploads } from "../../test/server";
import { subjectOfPart } from "./attachments";
import { DropZone } from "./DropZone";

const PART_ID = "0199cccc-0000-7000-8000-000000000001";
const subject = subjectOfPart(PART_ID);

// jsdom's File hides its bytes behind a buffer the request serializer can't read, so a
// multipart body built from one never reaches the handler. Node's own File does, and it is
// what the browser gives the DropZone anyway, so the test uses it.
function aFile(name: string, type: string, bytes = "data"): File {
  return new NodeFile([bytes], name, { type }) as unknown as File;
}

const pdf = aFile("bme280.pdf", "application/pdf", "%PDF-1.4");
const png = aFile("top.png", "image/png", "\x89PNG");

function render() {
  return renderWithProviders(<DropZone subject={subject} />);
}

/** Picks a file through the hidden file input, as the button click would open it. */
async function pick(user: ReturnType<typeof userEvent.setup>, file: File) {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("no file input");
  await user.upload(input, file);
}

describe("DropZone", () => {
  it("uploads a file picked with the button, guessing its kind from the type", async () => {
    const sent = acceptUploads();
    render();
    const user = userEvent.setup();

    await pick(user, pdf);
    // A PDF is suggested as a datasheet before the upload (requirement 6.2).
    expect(screen.getByRole("combobox")).toHaveValue("datasheet");

    await user.click(screen.getByRole("button", { name: "Add attachment" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ subject, kind: "datasheet", title: null, hasFile: true });
  });

  it("suggests image for a picture, and sends the kind the user changes it to", async () => {
    const sent = acceptUploads();
    render();
    const user = userEvent.setup();

    await pick(user, png);
    expect(screen.getByRole("combobox")).toHaveValue("image");

    await user.selectOptions(screen.getByRole("combobox"), "pinout_diagram");
    await user.click(screen.getByRole("button", { name: "Add attachment" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toMatchObject({ kind: "pinout_diagram", hasFile: true });
  });

  it("uploads a file dropped on the zone", async () => {
    const sent = acceptUploads();
    render();
    const user = userEvent.setup();

    const zone = screen.getByRole("button", { name: "Add a file" });
    fireEvent.drop(zone, { dataTransfer: { files: [pdf] } });

    // The dropped file is chosen, kind guessed; then the user confirms.
    expect(await screen.findByRole("combobox")).toHaveValue("datasheet");
    await user.click(screen.getByRole("button", { name: "Add attachment" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toMatchObject({ kind: "datasheet", hasFile: true });
  });

  it("says a file is too large on a 413 and keeps the chosen file", async () => {
    refuseUploads("the most a file may be is 25 MB", 413);
    render();
    const user = userEvent.setup();

    await pick(user, pdf);
    await user.click(screen.getByRole("button", { name: "Add attachment" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("too large");
    // The file stays chosen, so the section is as it was (requirement 6.3).
    expect(screen.getByRole("button", { name: "Add attachment" })).toBeInTheDocument();
  });

  it("says a file isn't a PDF or a picture on a 415", async () => {
    refuseUploads("only a PDF or a picture is accepted", 415);
    render();
    const user = userEvent.setup();

    await pick(user, pdf);
    await user.click(screen.getByRole("button", { name: "Add attachment" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("isn't a PDF or a picture");
  });

  it("says a file is already attached on a 409", async () => {
    refuseUploads("that file is already attached to this part", 409);
    render();
    const user = userEvent.setup();

    await pick(user, pdf);
    await user.click(screen.getByRole("button", { name: "Add attachment" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("already attached");
  });

  it("says the quota is reached on a 413 that mentions the space left", async () => {
    refuseUploads("only 2 MB of space is left in this workspace", 413);
    render();
    const user = userEvent.setup();

    await pick(user, pdf);
    await user.click(screen.getByRole("button", { name: "Add attachment" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("isn't enough space left");
  });
});
