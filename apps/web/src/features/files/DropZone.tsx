import type { AttachmentKind } from "@wiredex/api-client";
import { type Ref, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { PlusIcon } from "../../shared/ui/icons";
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
  const zone = useDropZone(owner);
  return (
    <div className="grid gap-3">
      <DropTarget zone={zone} variant="band" />
      <ChosenFile zone={zone} />
    </div>
  );
}

/** The state a drop target and its chosen-file panel share; the gallery places them apart. */
export function useDropZone(owner: AttachmentOwner) {
  const subject = subjectOf(owner);
  const upload = useUpload();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<AttachmentKind>("other");
  const [dragging, setDragging] = useState(false);
  const [refusal, setRefusal] = useState<RefusalKey | null>(null);

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

  const dragHandlers = {
    onDragOver: (event: React.DragEvent) => {
      event.preventDefault();
      setDragging(true);
    },
    onDragLeave: () => setDragging(false),
    onDrop: (event: React.DragEvent) => {
      event.preventDefault();
      setDragging(false);
      choose(event.dataTransfer.files[0] ?? null);
    },
  };

  return {
    owner,
    photos: owner.kind === "project",
    file,
    kind,
    setKind,
    dragging,
    refusal,
    inputRef,
    choose,
    reset,
    send,
    openPicker,
    dragHandlers,
    uploading: upload.isPending,
  };
}

export type DropZoneState = ReturnType<typeof useDropZone>;

/**
 * The button a file is dropped on or picked with, and the hidden input behind it. A band spans
 * its section with a hint; a tile is the size of a gallery thumbnail.
 */
export function DropTarget({
  zone,
  variant,
  ref,
}: {
  zone: DropZoneState;
  variant: "band" | "tile";
  ref?: Ref<HTMLButtonElement> | undefined;
}) {
  const { t } = useTranslation();
  const { photos, dragging } = zone;
  const look = dragging ? "border-primary bg-surface-2" : "border-border-strong bg-surface";

  return (
    <>
      {/* The drop zone doubles as a button: click or Enter/Space opens the file picker. */}
      {variant === "band" ? (
        <button
          ref={ref}
          type="button"
          aria-label={photos ? t("files.photos.uploadLabel") : t("files.upload.label")}
          onClick={zone.openPicker}
          {...zone.dragHandlers}
          className={`grid place-items-center gap-2 rounded-lg border-2 border-dashed p-6 text-center text-sm ${look}`}
        >
          <span className="text-muted">
            {photos ? t("files.photos.dropHint") : t("files.upload.dropHint")}
          </span>
          <span className="rounded-md border border-border-strong px-3 py-1.5 font-medium">
            {t("files.upload.choose")}
          </span>
        </button>
      ) : (
        <button
          ref={ref}
          type="button"
          onClick={zone.openPicker}
          {...zone.dragHandlers}
          className={`grid aspect-square w-full place-content-center justify-items-center gap-1 rounded-md border-2 border-dashed p-2 text-center text-sm text-muted hover:text-text ${look}`}
        >
          <PlusIcon />
          <span>{photos ? t("files.photos.uploadLabel") : t("files.upload.label")}</span>
        </button>
      )}

      <input
        ref={zone.inputRef}
        type="file"
        accept={acceptedTypes(zone.owner)}
        className="sr-only"
        onChange={(event) => zone.choose(event.target.files?.[0] ?? null)}
      />
    </>
  );
}

/** The file waiting to be sent: its name, its kind (not for a photo), a refusal, send, cancel. */
export function ChosenFile({ zone }: { zone: DropZoneState }) {
  const { t } = useTranslation();
  const kindId = useId();
  const { file, photos } = zone;
  if (!file) return null;

  return (
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
              value={zone.kind}
              onChange={(event) => zone.setKind(event.target.value as AttachmentKind)}
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

      {zone.refusal && (
        <p role="alert" className="text-sm text-crit">
          {t(zone.refusal)}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={zone.send}
          disabled={zone.uploading}
          className="rounded-md bg-primary px-4 py-2 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {zone.uploading
            ? t("files.upload.uploading", { name: file.name })
            : photos
              ? t("files.photos.add")
              : t("files.upload.add")}
        </button>
        <button
          type="button"
          onClick={zone.reset}
          className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
        >
          {t("files.upload.cancel")}
        </button>
      </div>
    </div>
  );
}
