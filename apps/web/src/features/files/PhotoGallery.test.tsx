import { File as NodeFile } from "node:buffer";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
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

async function openWall() {
  const user = userEvent.setup();
  renderGallery();
  const thumbnail = await screen.findByRole("button", {
    name: "Open Mounted on the wall full size",
  });
  await user.click(thumbnail);
  const dialog = screen.getByRole("dialog", { name: "Mounted on the wall" });
  return { user, thumbnail, dialog };
}

describe("PhotoGallery", () => {
  it("shows each photo as a lazy thumbnail named by its title", async () => {
    renderGallery();

    const wall = await screen.findByRole("img", { name: "Mounted on the wall" });
    expect(wall).toHaveAttribute("src", onTheWall.content_url);
    expect(wall).toHaveAttribute("loading", "lazy");
    expect(screen.getByRole("img", { name: "Inside the case" })).toHaveAttribute("loading", "lazy");
    const thumbnail = screen.getByRole("button", { name: "Open Mounted on the wall full size" });
    expect(thumbnail).toHaveAttribute("aria-haspopup", "dialog");
    // The photos are a block of their own, the add tile last among the thumbnails.
    const block = screen.getByRole("region", { name: "Photos" });
    const tiles = within(block).getAllByRole("listitem");
    expect(within(tiles.at(-1) as HTMLElement).getByRole("button")).toHaveAccessibleName(
      "Add a photo",
    );
  });

  it("says the project has no photos yet", async () => {
    renderGallery([]);

    expect(await screen.findByText("No photos yet.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Photos" })).toBeInTheDocument();
  });

  it("opens a photo full size in a dialog, with focus on Close", async () => {
    const { dialog } = await openWall();

    const image = within(dialog).getByRole("img", { name: "Mounted on the wall" });
    expect(image).toHaveAttribute("src", onTheWall.content_url);
    expect(within(dialog).getByRole("button", { name: "Close" })).toHaveFocus();
    const newTab = within(dialog).getByRole("link", { name: "Open in a new tab" });
    expect(newTab).toHaveAttribute("href", onTheWall.content_url);
    expect(newTab).toHaveAttribute("target", "_blank");
  });

  it("closes on Escape and puts focus back on the thumbnail", async () => {
    const { user, thumbnail } = await openWall();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(thumbnail).toHaveFocus();
  });

  it("closes with Close and puts focus back on the thumbnail", async () => {
    const { user, thumbnail, dialog } = await openWall();

    await user.click(within(dialog).getByRole("button", { name: "Close" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(thumbnail).toHaveFocus();
  });

  it("closes from the backdrop and puts focus back on the thumbnail", async () => {
    const { user, thumbnail } = await openWall();

    await user.click(screen.getByRole("button", { name: "Close the photo" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(thumbnail).toHaveFocus();
  });

  it("keeps Tab and Shift+Tab inside the dialog", async () => {
    const { user, dialog } = await openWall();

    for (let step = 0; step < 6; step += 1) {
      await user.tab();
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }
    for (let step = 0; step < 6; step += 1) {
      await user.tab({ shift: true });
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }
  });

  it("renames a photo from its dialog, keeping it an image", async () => {
    const sent = acceptAttachmentChanges();
    const { user, dialog } = await openWall();

    await user.click(within(dialog).getByRole("button", { name: "Rename Mounted on the wall" }));
    // A photo is an image: only its title is asked.
    expect(within(dialog).queryByRole("combobox", { name: "Kind" })).toBeNull();
    const title = within(dialog).getByRole("textbox", { name: "Title" });
    await user.clear(title);
    await user.type(title, "On the garden wall");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ title: "On the garden wall", kind: "image" });
  });

  it("asks before removing a photo, then closes the dialog and focuses the add tile", async () => {
    const { user, dialog } = await openWall();

    await user.click(within(dialog).getByRole("button", { name: "Remove Mounted on the wall" }));
    const question = within(dialog).getByRole("group", { name: "Remove this attachment?" });
    await user.click(within(question).getByRole("button", { name: "Remove attachment" }));

    await expect.poll(() => screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("img", { name: "Mounted on the wall" })).toBeNull();
    expect(screen.getByRole("img", { name: "Inside the case" })).toBeInTheDocument();
    // The close and the focus move are effects after the list's refetch, not part of it.
    await waitFor(() => expect(screen.getByRole("button", { name: "Add a photo" })).toHaveFocus());
  });

  it("adds a photo picked from the add tile, as an image of the project", async () => {
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

  it("refuses a PDF dropped on the add tile, in the photo wording", async () => {
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
});
