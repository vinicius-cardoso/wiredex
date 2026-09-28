import type { AttachmentKind, AttachmentResponse } from "@wiredex/api-client";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { ATTACHMENT_KINDS, useChangeAttachment, useDetach } from "./attachments";

type ControlProps = { attachment: AttachmentResponse; subject: string };

/**
 * Rename and re-kind in place; one PATCH carries whatever changed (requirement 4.1). A photo
 * hides the kind: a project's photos are images, so only the title is the owner's to change.
 */
export function AttachmentEditForm({
  attachment,
  subject,
  onClose,
  withKind = true,
}: ControlProps & { onClose: () => void; withKind?: boolean }) {
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
      {withKind && (
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
            {ATTACHMENT_KINDS.map((option) => (
              <option key={option} value={option}>
                {t(`files.kinds.${option}`)}
              </option>
            ))}
          </select>
        </div>
      )}
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

/** Opens the edit form; the title in its accessible name, "Rename board.png". */
export function RenameButton({ title, onClick }: { title: string; onClick: () => void }) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={t("files.renameTitle", { title })}
      className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
    >
      {t("files.rename")}
    </button>
  );
}

/** Removing asks first: an attachment's file may go with it (requirement 6.5). */
export function AttachmentRemoveButton({ attachment, subject }: ControlProps) {
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
