import type { FirmwareField } from "@wiredex/api-client";
import type { TFunction } from "i18next";
import { type ReactNode, useId } from "react";
import { useTranslation } from "react-i18next";
import { control } from "../inventory/StockDialog";
import { FirmwareRefusal } from "./firmware";
import { refusalKey } from "./labels";

export const MAX_NOTES_LENGTH = 500;

/** What the dialog chooses itself: the version, fixed on a unit, or the board, on a version. */
export type Choice = Extract<FirmwareField, "version" | "unit">;
/** The fields the dialog shows a refusal on; the rest are its own. */
type DialogField = Choice | Extract<FirmwareField, "flashed_at" | "notes">;
export type Problems = Partial<Record<DialogField, string>>;

/** What either form of the dialog is given: logging a flash made elsewhere, or making it. */
export type FormProps = {
  /** The choice made, the flash's unit and version; null while it isn't. */
  target: { unitId: string; versionId: string } | null;
  /** The field the dialog chooses, which a refusal about it lands on. */
  choice: Choice;
  /**
   * Shown on that field when the flash is logged before it is chosen. Without it *Log flash*
   * waits unavailable, for a choice the dialog can't offer and already says why.
   */
  unchosen?: string;
  /** The chosen firmware's board, such as `esp32:esp32:esp32`. */
  board: string;
  onClose: () => void;
  /** Told while the form can't be left, which only a write in progress asks. */
  onBusy: (busy: boolean) => void;
  /** The fields that make the choice, given the problem to show on them. */
  children: (problem: string | undefined) => ReactNode;
};

/** Notes as the API keeps them, trimmed and collapsed; blank ones are none (requirement 1.9). */
export function cleanNotes(notes: string): string {
  return notes.trim().replace(/\s+/g, " ");
}

type NotesProps = { value: string; onChange: (value: string) => void; problem: string | undefined };

export function NotesField({ value, onChange, problem }: NotesProps) {
  const { t } = useTranslation();
  const notesId = useId();
  return (
    <div className="grid gap-1">
      <label htmlFor={notesId} className="text-sm font-medium">
        {t("firmware.flash.dialog.notes")}
      </label>
      <input
        id={notesId}
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={control}
        aria-invalid={problem ? true : undefined}
        aria-describedby={`${notesId}-hint${problem ? ` ${notesId}-error` : ""}`}
      />
      <p id={`${notesId}-hint`} className="text-sm text-muted">
        {t("firmware.flash.dialog.notesHint", { max: MAX_NOTES_LENGTH })}
      </p>
      {problem && (
        <p id={`${notesId}-error`} className="text-sm text-crit">
          {problem}
        </p>
      )}
    </div>
  );
}

/**
 * A refused flash, as the sentences the dialog shows: on the field it names when the dialog
 * shows that field, the time, the notes or the dialog's own choice, from its code; a 404 says
 * the board or the version is gone; the rest, such as a retired unit on a unit's own dialog,
 * is the dialog's, the API's sentence when no code of ours fits.
 */
export function refusalOf(
  t: TFunction,
  error: unknown,
  choice: Choice,
): { fields: Problems; form: string | null } {
  if (!error) return { fields: {}, form: null };
  const refusal = error instanceof FirmwareRefusal ? error : null;
  if (refusal?.status === 404) return { fields: {}, form: t("firmware.flash.dialog.error.gone") };
  const key = refusalKey(refusal?.code ?? null);
  const sentence = key
    ? t(key, { item: refusal?.item ?? "" })
    : t("firmware.flash.dialog.error.save");
  const field = refusal?.field;
  if (field === choice || field === "flashed_at" || field === "notes") {
    return { fields: { [field]: sentence }, form: null };
  }
  return { fields: {}, form: sentence };
}
