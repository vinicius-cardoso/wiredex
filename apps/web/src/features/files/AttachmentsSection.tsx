import type { AttachmentKind, AttachmentResponse } from "@wiredex/api-client";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { subjectOfPart, useAttachments, useChangeAttachment, useDetach } from "./attachments";
import { DropZone } from "./DropZone";
import { formatSize } from "./sizes";

const KINDS: readonly AttachmentKind[] = ["datasheet", "image", "pinout_diagram", "other"];

/**
 * A part's attachments as the part page shows them: one row each with a kind, a title, a
 * size and a date, an image shown as a small preview. Each row opens in a new tab, downloads,
 * renames and re-kinds in place, or is removed after a confirmation (requirements 6.1, 6.4,
 * 6.5). A {@link DropZone} at the top adds one by drop or by picking a file (requirement 6.2).
 */
export function AttachmentsSection({ partId }: { partId: string }) {
  const { t } = useTranslation();
  const subject = subjectOfPart(partId);
  const attachments = useAttachments(subject);
  const headingId = useId();

  const items = attachments.data ?? [];

  return (
    <section aria-labelledby={headingId} className="grid gap-3">
      <h2 id={headingId} className="font-display text-xl font-semibold">
        {t("files.title")}
      </h2>

      <DropZone subject={subject} />

      {attachments.isPending && <p className="text-muted">{t("files.loading")}</p>}
      {attachments.isError && (
        <p role="alert" className="text-crit">
          {t("files.error")}
        </p>
      )}
      {attachments.isSuccess && items.length === 0 && (
        <p className="text-muted">{t("files.none")}</p>
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
        <a
          href={attachment.content_url}
          target="_blank"
          rel="noreferrer"
          aria-label={t("files.open", { title: attachment.title })}
          className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
        >
          {t("files.open", { title: attachment.title })}
        </a>
        <a
          href={`${attachment.content_url}?download=1`}
          download
          aria-label={t("files.download", { title: attachment.title })}
          className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
        >
          {t("files.download", { title: attachment.title })}
        </a>
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
        >
          {t("files.rename")}
        </button>
        <RemoveButton attachment={attachment} subject={subject} />
      </div>

      {editing && (
        <div className="sm:col-span-3">
          <EditForm attachment={attachment} subject={subject} onClose={() => setEditing(false)} />
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
      {t(`files.kinds.${attachment.kind}`).slice(0, 3).toUpperCase()}
    </span>
  );
}

/** Rename and re-kind in place; one PATCH carries whatever changed (requirement 4.1). */
function EditForm({
  attachment,
  subject,
  onClose,
}: {
  attachment: AttachmentResponse;
  subject: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const change = useChangeAttachment();
  const [title, setTitle] = useState(attachment.title);
  const [kind, setKind] = useState<AttachmentKind>(attachment.kind);
  const titleId = useId();
  const kindId = useId();

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    change.mutate(
      { attachmentId: attachment.id, subject, body: { title: title.trim(), kind } },
      { onSuccess: onClose },
    );
  };

  return (
    <form onSubmit={submit} className="grid gap-3 border-t border-border pt-3 sm:grid-cols-2">
      <div className="grid gap-1">
        <label htmlFor={titleId} className="text-sm font-medium">
          {t("files.titleLabel")}
        </label>
        <input
          id={titleId}
          type="text"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          className="rounded-md border border-border-strong bg-surface px-3 py-2 text-text"
        />
      </div>
      <div className="grid gap-1">
        <label htmlFor={kindId} className="text-sm font-medium">
          {t("files.kindLabel")}
        </label>
        <select
          id={kindId}
          value={kind}
          onChange={(event) => setKind(event.target.value as AttachmentKind)}
          className="rounded-md border border-border-strong bg-surface px-3 py-2 text-text"
        >
          {KINDS.map((option) => (
            <option key={option} value={option}>
              {t(`files.kinds.${option}`)}
            </option>
          ))}
        </select>
      </div>
      {change.isError && (
        <p role="alert" className="text-sm text-crit sm:col-span-2">
          {t("files.changeError")}
        </p>
      )}
      <div className="flex flex-wrap gap-3 sm:col-span-2">
        <button
          type="submit"
          disabled={change.isPending}
          className="rounded-md bg-primary px-4 py-2 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {change.isPending ? t("files.saving") : t("files.save")}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
        >
          {t("files.cancel")}
        </button>
      </div>
    </form>
  );
}

/** Removing asks first: an attachment's file may go with it (requirement 6.5). */
function RemoveButton({
  attachment,
  subject,
}: {
  attachment: AttachmentResponse;
  subject: string;
}) {
  const { t } = useTranslation();
  const detach = useDetach();
  const [asking, setAsking] = useState(false);

  if (!asking) {
    return (
      <button
        type="button"
        onClick={() => setAsking(true)}
        aria-label={t("files.removeTitle", { title: attachment.title })}
        className="rounded-md border border-crit px-3 py-1.5 text-sm text-crit hover:bg-surface-2"
      >
        {t("files.remove")}
      </button>
    );
  }

  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm">{t("files.removeQuestion")}</legend>
      {detach.isError && (
        <p role="alert" className="text-sm text-crit">
          {t("files.removeError")}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={detach.isPending}
          onClick={() => detach.mutate({ attachmentId: attachment.id, subject })}
          className="rounded-md bg-crit px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {t("files.removeConfirm")}
        </button>
        <button
          type="button"
          onClick={() => setAsking(false)}
          className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
        >
          {t("files.removeCancel")}
        </button>
      </div>
    </fieldset>
  );
}
