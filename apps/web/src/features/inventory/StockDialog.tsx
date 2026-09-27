import { type ReactNode, useEffect, useId } from "react";
import { useTranslation } from "react-i18next";

/** The shared input and button styles the three stock dialogs use, from theme tokens. */
export const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";
export const dialogPrimary =
  "rounded-md bg-primary px-4 py-2 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60";

type Props = { title: string; onClose: () => void; children: ReactNode };

/**
 * The shell the receive, adjust and move dialogs share: a labelled modal with a heading, a
 * backdrop that closes it, and Escape to leave. It is a `dialog` named by its heading, so a
 * screen reader announces what it is; the backdrop is a real button with an accessible name,
 * so a keyboard alone can shut it too (requirement 9.8).
 */
export function StockDialog({ title, onClose, children }: Props) {
  const { t } = useTranslation();
  const headingId = useId();

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <button
        type="button"
        aria-label={t("inventory.stock.closeBackdrop")}
        onClick={onClose}
        className="fixed inset-0 -z-10 cursor-default bg-black/40"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        className="grid w-full max-w-md gap-4 rounded-lg border border-border bg-surface p-6 shadow-lg"
      >
        <h3 id={headingId} className="font-display text-lg font-semibold">
          {title}
        </h3>
        {children}
      </div>
    </div>
  );
}
