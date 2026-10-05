import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Block, type BlockSpan } from "../../shared/ui/block";
import { subjectOf, useAttachments } from "./attachments";
import { ChosenFile, DropTarget, useDropZone } from "./DropZone";
import { PhotoViewer } from "./PhotoViewer";

/**
 * A project's photos as a gallery (requirement 10.8): small square thumbnails, each a button
 * that opens the photo full size in a dialog, where it is renamed and removed. The browser
 * scales the originals (the API serves no thumbnails) and loads them lazily. The last tile adds
 * a photo. They are the project's `files` attachments, so the list, the quota and the prune are
 * the ones a part's attachments have (requirement 7.7).
 */
export function PhotoGallery({
  projectId,
  span,
  tallOnXl,
}: {
  projectId: string;
  span?: BlockSpan | undefined;
  tallOnXl?: boolean | undefined;
}) {
  const { t } = useTranslation();
  const owner = { kind: "project", id: projectId } as const;
  const subject = subjectOf(owner);
  const photos = useAttachments(subject);
  const zone = useDropZone(owner);
  const [openId, setOpenId] = useState<string | null>(null);
  const [returning, setReturning] = useState(false);
  const openerRef = useRef<HTMLElement | null>(null);
  const tileRef = useRef<HTMLButtonElement>(null);

  const items = photos.data ?? [];
  const open = items.find((photo) => photo.id === openId);

  // A photo removed from the dialog closes it.
  useEffect(() => {
    if (openId !== null && photos.isSuccess && !open) {
      setOpenId(null);
      setReturning(true);
    }
  }, [openId, open, photos.isSuccess]);

  // Back on the thumbnail that opened the dialog once it has closed, or on the add tile when
  // that thumbnail went with its photo.
  useEffect(() => {
    if (!returning) return;
    const opener = openerRef.current;
    if (opener?.isConnected) opener.focus();
    else tileRef.current?.focus();
    setReturning(false);
  }, [returning]);

  function close() {
    setOpenId(null);
    setReturning(true);
  }

  return (
    <Block title={t("files.photos.title")} span={span} tallOnXl={tallOnXl}>
      {photos.isPending && <p className="text-muted">{t("files.photos.loading")}</p>}
      {photos.isError && (
        <p role="alert" className="text-crit">
          {t("files.photos.error")}
        </p>
      )}
      {photos.isSuccess && items.length === 0 && (
        <p className="text-muted">{t("files.photos.none")}</p>
      )}

      <ul className="grid grid-cols-[repeat(auto-fill,minmax(6rem,1fr))] gap-2">
        {items.map((photo) => (
          <li key={photo.id}>
            <button
              type="button"
              aria-haspopup="dialog"
              aria-label={t("files.photos.open", { title: photo.title })}
              title={photo.title}
              onClick={(event) => {
                openerRef.current = event.currentTarget;
                setOpenId(photo.id);
              }}
              className="block w-full overflow-hidden rounded-md border border-border hover:border-primary"
            >
              <img
                src={photo.content_url}
                alt={photo.title}
                loading="lazy"
                decoding="async"
                className="aspect-square w-full object-cover"
              />
            </button>
          </li>
        ))}
        <li className="relative">
          <DropTarget zone={zone} variant="tile" ref={tileRef} />
        </li>
      </ul>

      <ChosenFile zone={zone} />

      {open && <PhotoViewer photo={open} subject={subject} onClose={close} />}
    </Block>
  );
}
