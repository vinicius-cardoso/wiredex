import type { AttachmentResponse } from "@wiredex/api-client";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { AttachmentEditForm, AttachmentRemoveButton, RenameButton } from "./attachmentControls";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * One photo full size, in a modal dialog named by its title, with the controls the gallery's
 * thumbnails no longer have room for: open the original in a new tab, rename, remove. Escape,
 * Close and the backdrop close it; Tab stays inside while it is open. The gallery puts focus
 * back where it was.
 */
export function PhotoViewer({
  photo,
  subject,
  onClose,
}: {
  photo: AttachmentResponse;
  subject: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [editing, setEditing] = useState(false);
  // In a ref, so a new onClose from a re-render neither re-runs the effects nor moves focus.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      const active = document.activeElement;
      const inside = active instanceof Node && dialogRef.current.contains(active);
      if (event.shiftKey && (!inside || active === first)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (!inside || active === last)) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="fixed inset-0 z-50 grid overflow-y-auto p-4">
      <button
        type="button"
        tabIndex={-1}
        aria-label={t("files.photos.viewer.closeBackdrop")}
        onClick={() => onCloseRef.current()}
        className="fixed inset-0 -z-10 cursor-default bg-bg/80"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="m-auto grid w-full max-w-5xl gap-3 rounded-lg border border-border bg-surface p-4 shadow-lg"
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h2 id={titleId} className="min-w-0 font-display text-lg font-semibold wrap-anywhere">
            {photo.title}
          </h2>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <a
              href={photo.content_url}
              target="_blank"
              rel="noreferrer"
              className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
            >
              {t("files.photos.viewer.newTab")}
            </a>
            <button
              ref={closeRef}
              type="button"
              onClick={() => onCloseRef.current()}
              className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
            >
              {t("files.photos.viewer.close")}
            </button>
          </div>
        </div>
        <img
          src={photo.content_url}
          alt={photo.title}
          className="max-h-[75vh] w-full rounded-md object-contain"
        />
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
      </div>
    </div>
  );
}
