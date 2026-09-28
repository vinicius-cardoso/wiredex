import type { AttachmentResponse, MediaType } from "@wiredex/api-client";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { AttachmentEditForm, AttachmentRemoveButton, RenameButton } from "./attachmentControls";
import { type AttachmentOwner, subjectOf, useAttachments } from "./attachments";
import { DropZone } from "./DropZone";
import { formatSize } from "./sizes";

/**
 * An owner's attachments as a list: a part's *Attachments*, a revision's *Files*. One row
 * each with a kind, a title, a size and a date, an image shown as a small preview. Each row
 * opens in a new tab, downloads, renames and re-kinds in place, or is removed after a
 * confirmation (requirements 6.1, 6.4, 6.5). A {@link DropZone} at the top adds one by drop
 * or by picking a file (requirement 6.2). A project's photos are a gallery instead.
 */
export function AttachmentsSection({ owner }: { owner: AttachmentOwner }) {
  const { t } = useTranslation();
  const subject = subjectOf(owner);
  const attachments = useAttachments(subject);
  const headingId = useId();
  const onRevision = owner.kind === "revision";
  // A revision's files sit inside its panel, under the panel's own heading.
  const Heading = onRevision ? "h3" : "h2";

  const items = attachments.data ?? [];

  return (
    <section aria-labelledby={headingId} className="grid gap-3">
      <Heading id={headingId} className="font-display text-xl font-semibold">
        {onRevision ? t("files.revisionTitle") : t("files.title")}
      </Heading>

      <DropZone owner={owner} />

      {attachments.isPending && <p className="text-muted">{t("files.loading")}</p>}
      {attachments.isError && (
        <p role="alert" className="text-crit">
          {t("files.error")}
        </p>
      )}
      {attachments.isSuccess && items.length === 0 && (
        <p className="text-muted">{onRevision ? t("files.revisionNone") : t("files.none")}</p>
      )}

      {items.length > 0 && (
        <ul className="grid gap-2">
          {items.map((attachment) => (
            <li key={attachment.id}>
              <AttachmentRow attachment={attachment} subject={subject} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function AttachmentRow({
  attachment,
  subject,
}: {
  attachment: AttachmentResponse;
  subject: string;
}) {
  const { t, i18n } = useTranslation();
  const [editing, setEditing] = useState(false);

  const size = formatSize(attachment.size, i18n.language);
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" }).format(
    new Date(attachment.created_at),
  );
  const meta = t("files.meta", { kind: t(`files.kinds.${attachment.kind}`), size, date });

  return (
    <div className="grid gap-2 rounded-lg border border-border bg-surface p-3 sm:grid-cols-[auto_1fr_auto] sm:items-center">
      <Thumbnail attachment={attachment} />
      <div className="min-w-0">
        <p className="truncate font-medium">{attachment.title}</p>
        <p className="text-sm text-muted">{meta}</p>
      </div>
      <div className="flex flex-wrap gap-2 justify-self-start sm:justify-self-end">
        {/* Short labels, the title in each accessible name: "Open board.png" to a screen
            reader, without the buttons crowding the title out of the row. A ZIP has no
            Open: the API always sends it as a download, so a new tab would only save it. */}
        {previewable(attachment.media_type) && (
          <a
            href={attachment.content_url}
            target="_blank"
            rel="noreferrer"
            aria-label={t("files.open", { title: attachment.title })}
            className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
          >
            {t("files.openShort")}
          </a>
        )}
        <a
          href={`${attachment.content_url}?download=1`}
          download
          aria-label={t("files.download", { title: attachment.title })}
          className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
        >
          {t("files.downloadShort")}
        </a>
        <RenameButton title={attachment.title} onClick={() => setEditing(true)} />
        <AttachmentRemoveButton attachment={attachment} subject={subject} />
      </div>

      {editing && (
        <div className="sm:col-span-3">
          <AttachmentEditForm
            attachment={attachment}
            subject={subject}
            onClose={() => setEditing(false)}
          />
        </div>
      )}
    </div>
  );
}

/** A small preview for an image, the kind's name for anything else (requirement 6.1). */
function Thumbnail({ attachment }: { attachment: AttachmentResponse }) {
  const { t } = useTranslation();
  if (attachment.media_type.startsWith("image/")) {
    return (
      <img
        src={attachment.content_url}
        alt={t("files.preview", { title: attachment.title })}
        className="h-12 w-12 rounded-md border border-border object-cover"
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      className="grid h-12 w-12 place-items-center rounded-md border border-border bg-surface-2 text-xs text-muted"
    >
      {fileType(attachment.media_type)}
    </span>
  );
}

/** Whether a browser shows the type in place: a PDF or a picture, never a ZIP (as the API's
 * `MediaType.previewable`). */
function previewable(mediaType: MediaType): boolean {
  return mediaType !== "application/zip";
}

/** The badge of a file without a preview: its type, as people name it (PDF). */
function fileType(mediaType: string): string {
  return (mediaType.split("/")[1] ?? mediaType).toUpperCase();
}
