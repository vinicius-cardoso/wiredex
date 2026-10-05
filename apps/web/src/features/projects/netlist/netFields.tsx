import type { Net, NetChange, NetField, Netlist, WireColor } from "@wiredex/api-client";
import type { TFunction } from "i18next";
import { type RefObject, useId, useRef } from "react";
import { useTranslation } from "react-i18next";
import { netCell } from "./netCells";
import { NetRefusal } from "./netlist";
import { PinListInput } from "./PinListInput";
import { WireColorSelect } from "./WireColorSelect";

/** A net as its row holds it while it is typed. */
export type NetDraft = { name: string; color: WireColor | null; pins: string; notes: string };

export const emptyNet: NetDraft = { name: "", color: null, pins: "", notes: "" };

export const FIELD_ORDER: readonly NetField[] = ["name", "color", "pins", "notes"];

export type NetErrors = Partial<Record<NetField, string>>;

export function draftOf(net: Net): NetDraft {
  return { name: net.name, color: net.color, pins: net.pins_text, notes: net.notes ?? "" };
}

export function bodyOf(draft: NetDraft): NetChange {
  return {
    name: draft.name,
    color: draft.color,
    pins: draft.pins,
    notes: draft.notes.trim() ? draft.notes : null,
  };
}

export type NetFieldRefs = {
  name: RefObject<HTMLInputElement | null>;
  color: RefObject<HTMLSelectElement | null>;
  pins: RefObject<HTMLInputElement | null>;
  notes: RefObject<HTMLInputElement | null>;
};

export function useNetFieldRefs(): NetFieldRefs {
  return {
    name: useRef<HTMLInputElement>(null),
    color: useRef<HTMLSelectElement>(null),
    pins: useRef<HTMLInputElement>(null),
    notes: useRef<HTMLInputElement>(null),
  };
}

/** Each field's problem cleared once the field changes, so a fixed field stops showing it. */
export function withoutChanged(errors: NetErrors, before: NetDraft, after: NetDraft): NetErrors {
  return Object.fromEntries(
    Object.entries(errors).filter(
      ([field]) => before[field as NetField] === after[field as NetField],
    ),
  );
}

/**
 * A refused write, as the sentences the row shows: on the field it names, from its code, and
 * for a pin with the reference it refused (requirement 10.8); anything else under the row.
 */
export function refusalOf(
  t: TFunction,
  error: unknown,
  fallback: string,
): { fields: NetErrors; row: string | null } {
  if (!(error instanceof NetRefusal)) return { fields: {}, row: fallback };
  const sentence = error.code
    ? t(`projects.netlist.refusal.${error.code}`, {
        item: error.item ?? "",
        candidates: error.candidates.join(", "),
        net: error.net ?? "",
      })
    : error.detail || fallback;
  if (error.field) return { fields: { [error.field]: sentence }, row: null };
  return { fields: {}, row: sentence };
}

type Props = {
  draft: NetDraft;
  onChange: (draft: NetDraft) => void;
  errors: NetErrors;
  refs: NetFieldRefs;
  netlist: Netlist | undefined;
};

/** The four cells a net is typed in, shared by the add row and an edited row. */
export function NetFields({ draft, onChange, errors, refs, netlist }: Props) {
  const { t } = useTranslation();
  const ids = { name: useId(), color: useId(), pins: useId(), notes: useId() };
  const problem = (field: NetField) =>
    errors[field] ? (
      <p id={ids[field]} className="text-sm text-crit">
        {errors[field]}
      </p>
    ) : null;
  return (
    <>
      <td data-label={t("projects.netlist.columns.name")} className={netCell}>
        <label className="sr-only" htmlFor={`${ids.name}-input`}>
          {t("projects.netlist.editor.name")}
        </label>
        <input
          ref={refs.name}
          id={`${ids.name}-input`}
          type="text"
          value={draft.name}
          placeholder={t("projects.netlist.editor.namePlaceholder")}
          aria-invalid={errors.name ? true : undefined}
          aria-describedby={errors.name ? ids.name : undefined}
          onChange={(event) => onChange({ ...draft, name: event.target.value })}
          className="w-full min-w-24 rounded-md border border-border-strong bg-surface px-2 py-1.5 text-text"
        />
        {problem("name")}
      </td>
      <td data-label={t("projects.netlist.columns.color")} className={netCell}>
        <WireColorSelect
          ref={refs.color}
          label={t("projects.netlist.editor.color")}
          value={draft.color}
          onChange={(color) => onChange({ ...draft, color })}
        />
        {problem("color")}
      </td>
      <td data-label={t("projects.netlist.columns.pins")} className={netCell}>
        <PinListInput
          ref={refs.pins}
          label={t("projects.netlist.editor.pins")}
          value={draft.pins}
          netlist={netlist}
          invalid={Boolean(errors.pins)}
          describedBy={errors.pins ? ids.pins : undefined}
          onChange={(pins) => onChange({ ...draft, pins })}
        />
        {problem("pins")}
      </td>
      <td data-label={t("projects.netlist.columns.notes")} className={netCell}>
        <label className="sr-only" htmlFor={`${ids.notes}-input`}>
          {t("projects.netlist.editor.notes")}
        </label>
        <input
          ref={refs.notes}
          id={`${ids.notes}-input`}
          type="text"
          value={draft.notes}
          aria-invalid={errors.notes ? true : undefined}
          aria-describedby={errors.notes ? ids.notes : undefined}
          onChange={(event) => onChange({ ...draft, notes: event.target.value })}
          className="w-full min-w-24 rounded-md border border-border-strong bg-surface px-2 py-1.5 text-text"
        />
        {problem("notes")}
      </td>
    </>
  );
}
