import { File as NodeFile } from "node:buffer";
import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "../../test/render";
import {
  acceptAttachmentChanges,
  acceptUploads,
  anAttachment,
  refuseUploads,
  respondWithAttachments,
} from "../../test/server";
import { subjectOf } from "./attachments";
import { PhotoGallery } from "./PhotoGallery";

const PROJECT_ID = "0199eeee-0000-7000-8000-000000000001";
const subject = subjectOf({ kind: "project", id: PROJECT_ID });

const onTheWall = anAttachment({
  id: "0199eeee-0000-7000-8000-0000000000a1",
  subject,
  kind: "image",
  title: "Mounted on the wall",
  media_type: "image/jpeg",
  size: 240_000,
});

const inside = anAttachment({
  id: "0199eeee-0000-7000-8000-0000000000a2",
  subject,
  kind: "image",
  title: "Inside the case",
  media_type: "image/png",
  size: 180_000,
});

// Node's File, as in DropZone.test.tsx: jsdom's hides its bytes from the multipart body.
function aFile(name: string, type: string, bytes = "data"): File {
  return new NodeFile([bytes], name, { type }) as unknown as File;
}

function renderGallery(photos = [onTheWall, inside]) {
  respondWithAttachments(subject, photos);
  return renderWithProviders(<PhotoGallery projectId={PROJECT_ID} />);
}

describe("PhotoGallery", () => {
  it("shows each photo with its title as its text alternative, opening in a new tab", async () => {
    renderGallery();

    const wall = await screen.findByRole("img", { name: "Mounted on the wall" });
    expect(wall).toHaveAttribute("src", onTheWall.content_url);
    expect(screen.getByRole("img", { name: "Inside the case" })).toBeInTheDocument();

    const open = screen.getByRole("link", { name: "Open Mounted on the wall full size" });
    expect(open).toHaveAttribute("href", onTheWall.content_url);
    expect(open).toHaveAttribute("target", "_blank");
  });

  it("says the project has no photos yet", async () => {
    renderGallery([]);

    expect(await screen.findByText("No photos yet.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Photos" })).toBeInTheDocument();
  });

  it("adds a photo picked with the button, as an image of the project", async () => {
    const sent = acceptUploads();
    renderGallery([]);
    const user = userEvent.setup();
    await screen.findByText("No photos yet.");

    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("no file input");
    await user.upload(input, aFile("front.png", "image/png", "\x89PNG"));
    await user.click(screen.getByRole("button", { name: "Add photo" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ subject, kind: "image", title: null, hasFile: true });
  });

  it("refuses a PDF in the photo wording", async () => {
    refuseUploads("a project takes photos: PNG, JPEG or WebP", 415);
    renderGallery([]);
    const user = userEvent.setup();
    await screen.findByText("No photos yet.");

    fireEvent.drop(screen.getByRole("button", { name: "Add a photo" }), {
      dataTransfer: { files: [aFile("bme280.pdf", "application/pdf", "%PDF-1.4")] },
    });
    await user.click(await screen.findByRole("button", { name: "Add photo" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A project's photos are PNG, JPEG or WebP pictures.",
    );
  });

  it("renames a photo in place, keeping it an image", async () => {
    const sent = acceptAttachmentChanges();
    renderGallery();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Rename Mounted on the wall" }));
    // A photo is an image: only its title is asked.
    expect(screen.queryByRole("combobox", { name: "Kind" })).toBeNull();
    const title = screen.getByRole("textbox", { name: "Title" });
    await user.clear(title);
    await user.type(title, "On the garden wall");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ title: "On the garden wall", kind: "image" });
  });

  it("asks before removing a photo, then drops it from the gallery", async () => {
    renderGallery();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Remove Inside the case" }));
    const question = screen.getByRole("group", { name: "Remove this attachment?" });
    await user.click(within(question).getByRole("button", { name: "Remove attachment" }));

    await expect.poll(() => screen.queryByRole("img", { name: "Inside the case" })).toBeNull();
    expect(screen.getByRole("img", { name: "Mounted on the wall" })).toBeInTheDocument();
  });
});
