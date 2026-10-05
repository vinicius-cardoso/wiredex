import type { BomField, BomLine, BomLineChange, BomPart } from "@wiredex/api-client";
import type { TFunction } from "i18next";
import { type RefObject, useId, useRef } from "react";
import { useTranslation } from "react-i18next";
import { PartPicker, type PickedPart } from "../../catalog/PartPicker";
import { BomRefusal } from "./bom";
import { readDesignators } from "./designators";
import { blank, PartLink } from "./ShortageReport";
import { stockStatusKey, stockStatusTone } from "./stockStatus";

export const bomCell = "py-2 pr-4 align-top";

/** A line as its row holds it while it is typed: every field as text, the part as picked. */
export type LineDraft = {
  designators: string;
  part: PickedPart | null;
  quantity: string;
  notes: string;
};

export const emptyDraft: LineDraft = { designators: "", part: null, quantity: "", notes: "" };

/** Each field's problem, in the reader's language. */
export type FieldErrors = Partial<Record<BomField, string>>;

/** A line as its edit starts: what it holds, its designators in canonical text. */
export function draftOf(t: TFunction, line: BomLine, part: BomPart | undefined): LineDraft {
  return {
    designators: line.designator_text,
    part: { id: line.part_id, name: part?.part?.name ?? t("projects.bom.unknownPart") },
    quantity: String(line.quantity),
    notes: line.notes ?? "",
  };
}

/**
 * The body of a line write. With designators the quantity is left to their count, so it can
 * never disagree with them (decision 7); without, what is typed goes, and the server refuses a
 * blank or a bad one on the quantity.
 */
export function bodyOf(draft: LineDraft, partId: string): BomLineChange {
  const quantity = Number(draft.quantity);
  const typed = draft.quantity.trim() !== "" && Number.isFinite(quantity);
  return {
    part_id: partId,
    designators: draft.designators,
    quantity: draft.designators.trim() === "" && typed ? quantity : null,
    notes: draft.notes,
  };
}

/** A line as its buttons name it: by its designators, or by its part when it has none. */
export function lineName(t: TFunction, line: BomLine, part: BomPart | undefined): string {
  return line.designator_text || (part?.part?.name ?? t("projects.bom.unknownPart"));
}

/**
 * Where a refused write lands (requirement 11.7): on the field it names, as the sentence for
 * its code, or on the row when it names none, as a locked BOM or a 501st line does.
 */
export function refusalOf(
  t: TFunction,
  error: unknown,
  fallback: string,
): { fields: FieldErrors; row: string | null } {
  if (!(error instanceof BomRefusal)) return { fields: {}, row: fallback };
  const sentence = error.code
    ? t(`projects.bom.refusal.${error.code}`, { item: error.item ?? "", line: error.line ?? "" })
    : error.detail || fallback;
  return error.field
    ? { fields: { [error.field]: sentence }, row: null }
    : { fields: {}, row: sentence };
}

/** The problems left once a field changes: a field that was typed in again drops its own. */
export function withoutChanged(errors: FieldErrors, before: LineDraft, after: LineDraft) {
  const changed: Record<BomField, boolean> = {
    designators: before.designators !== after.designators,
    part: before.part?.id !== after.part?.id,
    // The quantity follows the designators while they are given.
    quantity: before.quantity !== after.quantity || before.designators !== after.designators,
    notes: before.notes !== after.notes,
  };
  return Object.fromEntries(
    Object.entries(errors).filter(([field]) => !changed[field as BomField]),
  ) as FieldErrors;
}

/** The four fields' boxes, so a row can focus the one a refusal names. */
export type LineFieldRefs = Record<BomField, RefObject<HTMLInputElement | null>>;

export function useLineFieldRefs(): LineFieldRefs {
  return {
    designators: useRef<HTMLInputElement>(null),
    part: useRef<HTMLInputElement>(null),
    quantity: useRef<HTMLInputElement>(null),
    notes: useRef<HTMLInputElement>(null),
  };
}

/** The fields in the order the row reads them, so the first refused one takes focus. */
export const FIELD_ORDER: BomField[] = ["designators", "part", "quantity", "notes"];

const box = "w-full rounded-md border border-border-strong bg-surface px-2 py-1.5 text-text";

type Props = {
  draft: LineDraft;
  onChange: (draft: LineDraft) => void;
  errors: FieldErrors;
  refs: LineFieldRefs;
};

/**
 * A line's four cells as fields, for the add row and a row being edited (requirements 11.2,
 * 11.3, 11.5). Designators come first and describe themselves with a preview of their
 * canonical text and count; while any are typed, the quantity is that count and can't be
 * edited. A refused field is marked invalid, with its sentence as its description.
 */
export function LineFields({ draft, onChange, errors, refs }: Props) {
  const { t } = useTranslation();
  const previewId = useId();
  const quantityHintId = useId();
  const errorIds = {
    designators: useId(),
    part: useId(),
    quantity: useId(),
    notes: useId(),
  };
  const reading = readDesignators(draft.designators);
  const byDesignators = draft.designators.trim() !== "";

  let preview = "";
  if (reading.problem) {
    preview = t(`projects.bom.refusal.${reading.problem.code}`, {
      item: reading.problem.item ?? "",
      line: "",
    });
  } else if (reading.count > 0) {
    preview = t("projects.bom.editor.preview", { text: reading.text, count: reading.count });
  }

  const set = (change: Partial<LineDraft>) => onChange({ ...draft, ...change });
  const describedBy = (field: BomField, ...others: string[]) =>
    [...others, errors[field] ? errorIds[field] : null].filter(Boolean).join(" ") || undefined;
  const problem = (field: BomField) =>
    errors[field] && (
      <p id={errorIds[field]} className="text-sm text-crit">
        {errors[field]}
      </p>
    );

  return (
    <>
      <td data-label={t("projects.bom.columns.designators")} className={bomCell}>
        <div className="grid gap-1">
          <input
            ref={refs.designators}
            type="text"
            aria-label={t("projects.bom.columns.designators")}
            aria-describedby={describedBy("designators", previewId)}
            aria-invalid={errors.designators ? true : undefined}
            autoComplete="off"
            spellCheck={false}
            placeholder={t("projects.bom.editor.designatorsPlaceholder")}
            value={draft.designators}
            onChange={(event) => set({ designators: event.target.value })}
            className={`${box} min-w-28 font-mono`}
          />
          <p id={previewId} className={`text-sm ${reading.problem ? "text-warn" : "text-muted"}`}>
            {preview}
          </p>
          {problem("designators")}
        </div>
      </td>
      <td data-label={t("projects.bom.columns.part")} className={bomCell}>
        <div className="grid gap-1">
          <PartPicker
            ref={refs.part}
            label={t("projects.bom.columns.part")}
            labelHidden
            value={draft.part}
            onChange={(part) => set({ part })}
            {...(errors.part ? { describedBy: errorIds.part, invalid: true } : {})}
          />
          {problem("part")}
        </div>
      </td>
      <td data-label={t("projects.bom.columns.quantity")} className={bomCell}>
        <div className="grid gap-1">
          <input
            ref={refs.quantity}
            type="number"
            inputMode="numeric"
            min={1}
            max={10_000}
            step={1}
            aria-label={t("projects.bom.columns.quantity")}
            aria-describedby={describedBy("quantity", ...(byDesignators ? [quantityHintId] : []))}
            aria-invalid={errors.quantity ? true : undefined}
            readOnly={byDesignators}
            value={byDesignators ? (reading.count ?? "") : draft.quantity}
            onChange={(event) => set({ quantity: event.target.value })}
            className={`${box} w-20 read-only:bg-surface-2 read-only:text-muted`}
          />
          {byDesignators && (
            <p id={quantityHintId} className="sr-only">
              {t("projects.bom.editor.quantityFromDesignators")}
            </p>
          )}
          {problem("quantity")}
        </div>
      </td>
      <td data-label={t("projects.bom.columns.notes")} className={bomCell}>
        <div className="grid gap-1">
          <input
            ref={refs.notes}
            type="text"
            aria-label={t("projects.bom.columns.notes")}
            aria-describedby={describedBy("notes")}
            aria-invalid={errors.notes ? true : undefined}
            value={draft.notes}
            onChange={(event) => set({ notes: event.target.value })}
            className={`${box} min-w-32`}
          />
          {problem("notes")}
        </div>
      </td>
    </>
  );
}

/** A line's five cells as they read when it isn't being edited. */
export function LineCells({ line, part }: { line: BomLine; part: BomPart | undefined }) {
  const { t } = useTranslation();
  return (
    <>
      <td data-label={t("projects.bom.columns.designators")} className={`${bomCell} font-mono`}>
        {line.designator_text || blank}
      </td>
      <td data-label={t("projects.bom.columns.part")} className={bomCell}>
        {part ? <PartLink part={part} /> : blank}
        {part?.part?.mpn && <span className="block font-mono text-muted">{part.part.mpn}</span>}
      </td>
      <td data-label={t("projects.bom.columns.quantity")} className={bomCell}>
        {line.quantity}
      </td>
      <td data-label={t("projects.bom.columns.notes")} className={bomCell}>
        {line.notes ?? blank}
      </td>
      <td
        data-label={t("projects.bom.columns.stock")}
        className={`${bomCell} ${part ? stockStatusTone[part.status] : ""}`}
      >
        {part ? t(stockStatusKey(part.status)) : blank}
      </td>
    </>
  );
}
