import type { AttachmentResponse } from "@wiredex/api-client";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { AttachmentEditForm, AttachmentRemoveButton, RenameButton } from "./attachmentControls";
import { subjectOf, useAttachments } from "./attachments";
import { DropZone } from "./DropZone";

/**
 * A project's photos as a gallery (requirement 10.8): a grid of figures, each image's text
 * alternative its title, opening full size in a new tab, renamed and removed in place. They
 * are the project's `files` attachments, so the list, the quota and the prune are the ones a
 * part's attachments have (requirement 7.7).
 */
export function PhotoGallery({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const owner = { kind: "project", id: projectId } as const;
  const subject = subjectOf(owner);
  const photos = useAttachments(subject);
  const headingId = useId();

  const items = photos.data ?? [];

  return (
    <section aria-labelledby={headingId} className="grid gap-3">
      <h2 id={headingId} className="font-display text-xl font-semibold">
        {t("files.photos.title")}
      </h2>

      {photos.isPending && <p className="text-muted">{t("files.photos.loading")}</p>}
      {photos.isError && (
        <p role="alert" className="text-crit">
          {t("files.photos.error")}
        </p>
      )}
      {photos.isSuccess && items.length === 0 && (
        <p className="text-muted">{t("files.photos.none")}</p>
      )}

      {items.length > 0 && (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {items.map((photo) => (
            <li key={photo.id}>
              <Photo photo={photo} subject={subject} />
            </li>
          ))}
        </ul>
      )}

      <DropZone owner={owner} />
    </section>
  );
}

function Photo({ photo, subject }: { photo: AttachmentResponse; subject: string }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);

  return (
    <figure className="grid gap-2 rounded-lg border border-border bg-surface p-2">
      <a
        href={photo.content_url}
        target="_blank"
        rel="noreferrer"
        aria-label={t("files.photos.open", { title: photo.title })}
        className="block rounded-md"
      >
        <img
          src={photo.content_url}
          alt={photo.title}
          className="aspect-square w-full rounded-md border border-border object-cover"
        />
      </a>
      <figcaption className="truncate text-sm font-medium">{photo.title}</figcaption>
      <div className="flex flex-wrap gap-2">
        <RenameButton title={photo.title} onClick={() => setEditing(true)} />
        <AttachmentRemoveButton attachment={photo} subject={subject} />
      </div>
      {editing && (
        <AttachmentEditForm
          attachment={photo}
          subject={subject}
          withKind={false}
          onClose={() => setEditing(false)}
        />
      )}
    </figure>
  );
}
