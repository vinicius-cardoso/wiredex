import type { AttachmentKind } from "@wiredex/api-client";
import { useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { type RefusalKey, refusalKey, UploadRefusal, useUpload } from "./attachments";

const KINDS: readonly AttachmentKind[] = ["datasheet", "image", "pinout_diagram", "other"];

/** PDF → datasheet, an image → image, anything else → other (requirement 6.2). */
function suggestedKind(file: File): AttachmentKind {
  if (file.type === "application/pdf") return "datasheet";
  if (file.type.startsWith("image/")) return "image";
  return "other";
}

/**
 * Adds a file to a part: drop one on the zone or pick it with a button, both reachable by
 * keyboard (requirements 6.2, 6.6). A picked file's kind is guessed from its type and can be
 * changed before the upload. A refusal shows its own words in place and keeps the chosen
 * file, so nothing is lost and the section stays as it was (requirement 6.3).
 */
export function DropZone({ subject }: { subject: string }) {
  const { t } = useTranslation();
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
    setKind(suggestedKind(chosen));
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
            error instanceof UploadRefusal ? refusalKey(error) : "files.upload.refused.other",
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
        aria-label={t("files.upload.label")}
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
        <span className="text-muted">{t("files.upload.dropHint")}</span>
        <span className="rounded-md border border-border-strong px-3 py-1.5 font-medium">
          {t("files.upload.choose")}
        </span>
      </button>

      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,image/png,image/jpeg,image/webp"
        className="sr-only"
        onChange={(event) => choose(event.target.files?.[0] ?? null)}
      />

      {file && (
        <div className="grid gap-3 rounded-lg border border-border bg-surface p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="min-w-0 truncate font-medium">
              {t("files.upload.chosen", { name: file.name })}
            </span>
            <label htmlFor={kindId} className="sr-only">
              {t("files.kindLabel")}
            </label>
            <select
              id={kindId}
              value={kind}
              onChange={(event) => setKind(event.target.value as AttachmentKind)}
              className="rounded-md border border-border-strong bg-surface px-3 py-1.5 text-sm text-text"
            >
              {KINDS.map((option) => (
                <option key={option} value={option}>
                  {t(`files.kinds.${option}`)}
                </option>
              ))}
            </select>
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
