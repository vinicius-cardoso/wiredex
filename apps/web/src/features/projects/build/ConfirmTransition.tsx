import { useEffect, useId, useRef } from "react";
import { useTranslation } from "react-i18next";
import { LifecycleRefusal } from "./lifecycle";
import { refusalMessage } from "./refusal";

const primary =
  "rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60";
const secondary = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";

type Props = {
  /** The question the group is named by, e.g. "Build revision A?". */
  question: string;
  confirmLabel: string;
  pending: boolean;
  error: unknown;
  onConfirm: () => void;
  onCancel: () => void;
};

/**
 * *Build* and *Cancel reservation* turn, in place, into a question with a confirm and a
 * back-out button (requirement 13.4). The group is named by the question; focus lands on the
 * confirm when it opens, and Escape backs out, so the whole thing works by keyboard alone
 * (requirement 13.15). A refusal shows in the reader's language, from its code (13.13).
 */
export function ConfirmTransition({
  question,
  confirmLabel,
  pending,
  error,
  onConfirm,
  onCancel,
}: Props) {
  const { t } = useTranslation();
  const messageId = useId();
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    confirmRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onCancel();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const refusal = error instanceof LifecycleRefusal ? error : null;
  const message = error ? refusalMessage(t, refusal) : "";

  return (
    <fieldset className="grid gap-2" aria-describedby={message ? messageId : undefined}>
      <legend className="text-sm">{question}</legend>
      {message && (
        <p id={messageId} role="alert" className="text-sm text-crit">
          {message}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          ref={confirmRef}
          type="button"
          disabled={pending}
          onClick={onConfirm}
          className={primary}
        >
          {confirmLabel}
        </button>
        <button type="button" onClick={onCancel} className={secondary}>
          {t("projects.lifecycle.confirm.back")}
        </button>
      </div>
    </fieldset>
  );
}
