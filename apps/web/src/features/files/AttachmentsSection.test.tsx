import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "../../test/render";
import {
  acceptAttachmentChanges,
  anAttachment,
  refuseAttachmentChanges,
  refuseAttachmentRemoval,
  respondWithAttachments,
  server,
} from "../../test/server";
import { AttachmentsSection } from "./AttachmentsSection";
import { subjectOfPart } from "./attachments";

const PART_ID = "0199cccc-0000-7000-8000-000000000001";
const subject = subjectOfPart(PART_ID);

const datasheet = anAttachment({
  id: "0199eeee-0000-7000-8000-000000000001",
  subject,
  kind: "datasheet",
  title: "BME280 datasheet",
  media_type: "application/pdf",
  size: 1_258_291,
});

const photo = anAttachment({
  id: "0199eeee-0000-7000-8000-000000000002",
  subject,
  kind: "image",
  title: "Top view",
  media_type: "image/png",
  size: 48_000,
});

function renderSection(attachments = [datasheet, photo]) {
  respondWithAttachments(subject, attachments);
  return renderWithProviders(<AttachmentsSection partId={PART_ID} />);
}

/** The list items, one per attachment. */
async function rows() {
  const list = await screen.findByRole("list");
  return within(list).getAllByRole("listitem");
}

describe("AttachmentsSection", () => {
  it("lists each attachment with its kind, size and date", async () => {
    renderSection();

    const items = await rows();
    expect(items).toHaveLength(2);
    expect(within(items[0] as HTMLElement).getByText("BME280 datasheet")).toBeInTheDocument();
    expect(within(items[0] as HTMLElement).getByText(/Datasheet · 1\.2 MB · /)).toBeInTheDocument();
  });

  it("shows an image as a preview and a document as its kind", async () => {
    renderSection();
    await rows();

    const preview = screen.getByRole("img", { name: "Preview of Top view" });
    expect(preview).toHaveAttribute("src", photo.content_url);
    // The PDF has no preview image, only the image does.
    expect(screen.getAllByRole("img")).toHaveLength(1);
  });

  it("opens an attachment in a new tab and offers a download", async () => {
    renderSection();
    await rows();

    const open = screen.getByRole("link", { name: "Open BME280 datasheet" });
    expect(open).toHaveAttribute("href", datasheet.content_url);
    expect(open).toHaveAttribute("target", "_blank");

    const download = screen.getByRole("link", { name: "Download BME280 datasheet" });
    expect(download).toHaveAttribute("href", `${datasheet.content_url}?download=1`);
    expect(download).toHaveAttribute("download");
  });

  it("renames and re-kinds an attachment in place", async () => {
    renderSection();
    const sent = acceptAttachmentChanges();
    await rows();
    const user = userEvent.setup();

    const [first] = await rows();
    await user.click(within(first as HTMLElement).getByRole("button", { name: "Rename" }));

    const title = await screen.findByRole("textbox", { name: "Title" });
    await user.clear(title);
    await user.type(title, "Datasheet rev B");
    await user.selectOptions(screen.getByRole("combobox", { name: "Kind" }), "other");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]).toEqual({ title: "Datasheet rev B", kind: "other" });
  });

  it("says so when a change is refused, keeping the form open", async () => {
    renderSection();
    refuseAttachmentChanges("that title is too long");
    await rows();
    const user = userEvent.setup();

    const [first] = await rows();
    await user.click(within(first as HTMLElement).getByRole("button", { name: "Rename" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't be saved");
    // Still editing: the title field is still there.
    expect(screen.getByRole("textbox", { name: "Title" })).toBeInTheDocument();
  });

  it("asks before removing an attachment, then drops it from the list", async () => {
    renderSection();
    await rows();
    const user = userEvent.setup();

    const [first] = await rows();
    await user.click(
      within(first as HTMLElement).getByRole("button", { name: "Remove BME280 datasheet" }),
    );

    const question = screen.getByRole("group", { name: "Remove this attachment?" });
    expect(question).toBeInTheDocument();
    await user.click(within(question).getByRole("button", { name: "Remove attachment" }));

    // The list refetches without it; the image attachment is the only one left.
    await expect.poll(() => screen.queryByText("BME280 datasheet")).toBeNull();
    expect(screen.getByText("Top view")).toBeInTheDocument();
  });

  it("says so when a removal is refused", async () => {
    renderSection();
    refuseAttachmentRemoval("the file store can't be reached right now");
    await rows();
    const user = userEvent.setup();

    const [first] = await rows();
    await user.click(
      within(first as HTMLElement).getByRole("button", { name: "Remove BME280 datasheet" }),
    );
    const question = screen.getByRole("group", { name: "Remove this attachment?" });
    await user.click(within(question).getByRole("button", { name: "Remove attachment" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't be removed");
  });

  it("says the part has no attachments yet", async () => {
    renderSection([]);

    expect(await screen.findByText("No attachments yet.")).toBeInTheDocument();
  });

  it("says so when the attachments can't be loaded", async () => {
    server.use(http.get("*/api/files/attachments", () => HttpResponse.error()));
    renderWithProviders(<AttachmentsSection partId={PART_ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't be loaded");
  });
});
