import type { AttachmentKind } from "@wiredex/api-client";
import { useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ATTACHMENT_KINDS,
  type AttachmentOwner,
  acceptedTypes,
  type RefusalKey,
  refusalKey,
  subjectOf,
  suggestedKind,
  UploadRefusal,
  useUpload,
} from "./attachments";

/**
 * Adds a file to its owner: drop one on the zone or pick it with a button, both reachable by
 * keyboard (requirements 6.2, 6.6). A picked file's kind is suggested from its type and the
 * owner (a revision's PDF is a schematic, a part's a datasheet) and can be changed before the
 * upload. A project takes photos, so its zone offers pictures only and asks no kind. A refusal
 * shows its own words in place and keeps the chosen file, so nothing is lost and the section
 * stays as it was (requirement 6.3).
 */
export function DropZone({ owner }: { owner: AttachmentOwner }) {
  const { t } = useTranslation();
  const subject = subjectOf(owner);
  const photos = owner.kind === "project";
  const upload = useUpload();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<AttachmentKind>("other");
  const [dragging, setDragging] = useState(false);
  const [refusal, setRefusal] = useState<RefusalKey | null>(null);
  const kindId = useId();

  const choose = (chosen: File | null) => {
    if (!chosen) return;
    setFile(chosen);
    setKind(suggestedKind(owner, chosen.type));
    setRefusal(null);
  };

  const reset = () => {
    setFile(null);
    setRefusal(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  const send = () => {
    if (!file) return;
    setRefusal(null);
    upload.mutate(
      { subject, kind, file },
      {
        onSuccess: reset,
        onError: (error) => {
          setRefusal(
            error instanceof UploadRefusal
              ? refusalKey(error, owner.kind)
              : "files.upload.refused.other",
          );
        },
      },
    );
  };

  const openPicker = () => inputRef.current?.click();

  return (
    <div className="grid gap-3">
      {/* The drop zone doubles as a button: click or Enter/Space opens the file picker. */}
      <button
        type="button"
        aria-label={photos ? t("files.photos.uploadLabel") : t("files.upload.label")}
        onClick={openPicker}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          choose(event.dataTransfer.files[0] ?? null);
        }}
        className={`grid place-items-center gap-2 rounded-lg border-2 border-dashed p-6 text-center text-sm ${
          dragging ? "border-primary bg-surface-2" : "border-border-strong bg-surface"
        }`}
      >
        <span className="text-muted">
          {photos ? t("files.photos.dropHint") : t("files.upload.dropHint")}
        </span>
        <span className="rounded-md border border-border-strong px-3 py-1.5 font-medium">
          {t("files.upload.choose")}
        </span>
      </button>

      <input
        ref={inputRef}
        type="file"
        accept={acceptedTypes(owner)}
        className="sr-only"
        onChange={(event) => choose(event.target.files?.[0] ?? null)}
      />

      {file && (
        <div
          // One minmax(0, 1fr) column: the name below doesn't wrap, and without it the name's
          // full width would widen the page on a phone instead of being cut short.
          className="grid grid-cols-1 gap-3 rounded-lg border border-border bg-surface p-3"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="min-w-0 truncate font-medium">
              {photos
                ? t("files.photos.chosen", { name: file.name })
                : t("files.upload.chosen", { name: file.name })}
            </span>
            {!photos && (
              <>
                <label htmlFor={kindId} className="sr-only">
                  {t("files.kindLabel")}
                </label>
                <select
                  id={kindId}
                  value={kind}
                  onChange={(event) => setKind(event.target.value as AttachmentKind)}
                  className="rounded-md border border-border-strong bg-surface px-3 py-1.5 text-sm text-text"
                >
                  {ATTACHMENT_KINDS.map((option) => (
                    <option key={option} value={option}>
                      {t(`files.kinds.${option}`)}
                    </option>
                  ))}
                </select>
              </>
            )}
          </div>

          {refusal && (
            <p role="alert" className="text-sm text-crit">
              {t(refusal)}
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={send}
              disabled={upload.isPending}
              className="rounded-md bg-primary px-4 py-2 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
            >
              {upload.isPending
                ? t("files.upload.uploading", { name: file.name })
                : photos
                  ? t("files.photos.add")
                  : t("files.upload.add")}
            </button>
            <button
              type="button"
              onClick={reset}
              className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
            >
              {t("files.upload.cancel")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
