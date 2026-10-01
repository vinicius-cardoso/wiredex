import { useQuery } from "@tanstack/react-query";
import type { UnitResponse } from "@wiredex/api-client";
import { type ChangeEvent, type KeyboardEvent, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { unitSearchQuery } from "./units";

/** How long typing pauses before the picker asks, so a code typed whole is one search. */
const PAUSE_MS = 200;

/** A picked unit: its id, and the code the box shows while it is picked. */
export type PickedUnit = { id: string; code: string };

type Props = {
  /** The label, which is also the combobox's accessible name. */
  label: string;
  /** The picked unit, or null while none is picked. */
  value: PickedUnit | null;
  /** Gets the unit picked, or null when the box is emptied. */
  onChange: (unit: PickedUnit | null) => void;
  /** Ids of what describes the field, such as a problem shown under it. */
  describedBy?: string | undefined;
  /** Marks the field as refused, beside a problem that says why. */
  invalid?: boolean;
};

/**
 * Picks a unit by typing part of its code, serial or MAC (spec 15, requirement 8.3), over 06's
 * unit search once typing pauses. In `features/inventory` beside the search page, since any
 * screen that names a board can pick it here.
 *
 * It is the WAI-ARIA combobox with a list popup and manual selection, as catalog's `PartPicker`
 * is: typing opens the matches, each with its code, its status in words and the serial and MAC
 * it was found by; the arrows move through them, Enter picks the one moved to, and Escape
 * shuts the list. A retired unit is listed, so it isn't mistaken for one that doesn't exist,
 * but it is unavailable: `aria-disabled`, saying so in words, and neither Enter nor a click
 * picks it. The list sits in the flow under the box rather than floating, as `PartPicker`'s.
 */
export function UnitPicker({ label, value, onChange, describedBy, invalid = false }: Props) {
  const { t } = useTranslation();
  const inputId = useId();
  const labelId = useId();
  const listId = useId();

  const pickedText = value?.code ?? "";
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const found = useUnitSuggestions(open ? draft : "");

  const text = open ? draft : pickedText;
  const matches = open ? (found.units ?? []) : [];
  const active = matches.find((unit) => unit.id === activeId);
  const expanded = matches.length > 0;
  const optionId = (unit: UnitResponse) => `${listId}-${unit.id}`;
  const activeOptionId = active ? optionId(active) : undefined;

  useEffect(() => {
    if (!activeOptionId) return;
    // jsdom has no scrollIntoView, hence the optional call.
    document.getElementById(activeOptionId)?.scrollIntoView?.({ block: "nearest" });
  }, [activeOptionId]);

  function pick(unit: UnitResponse) {
    if (unit.status === "retired") return;
    onChange({ id: unit.id, code: unit.code });
    setOpen(false);
    setActiveId(null);
  }

  function type(event: ChangeEvent<HTMLInputElement>) {
    const typed = event.target.value;
    setDraft(typed);
    setOpen(true);
    setActiveId(null);
    if (typed.trim() === "" && value !== null) onChange(null);
  }

  function step(by: 1 | -1) {
    if (matches.length === 0) return;
    const at = matches.findIndex((unit) => unit.id === activeId);
    const next =
      at === -1 ? (by === 1 ? 0 : matches.length - 1) : (at + by + matches.length) % matches.length;
    setActiveId(matches[next]?.id ?? null);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (open) {
        step(event.key === "ArrowDown" ? 1 : -1);
      } else if (pickedText) {
        // Opens on the picked unit's code, so its neighbours can be reached from the keys.
        setDraft(pickedText);
        setOpen(true);
      }
    } else if (event.key === "Enter" && open) {
      // Picks rather than submits the form, even when nothing is moved to or it is retired.
      event.preventDefault();
      if (active) pick(active);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
    }
  }

  let status = "";
  if (open && draft.trim() !== "") {
    if (found.isError) status = t("inventory.units.picker.error");
    else if (found.isPending) status = t("inventory.units.picker.loading");
    else if (matches.length === 0) status = t("inventory.units.picker.none");
    else status = t("inventory.units.picker.count", { count: matches.length });
  }

  return (
    <div className="grid gap-1">
      <label id={labelId} htmlFor={inputId} className="text-sm font-medium">
        {label}
      </label>
      <input
        id={inputId}
        type="text"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={expanded}
        aria-controls={listId}
        aria-activedescendant={activeOptionId}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        autoComplete="off"
        spellCheck={false}
        value={text}
        placeholder={t("inventory.units.picker.placeholder")}
        onChange={type}
        onKeyDown={onKeyDown}
        onBlur={() => setOpen(false)}
        className="w-full min-w-40 rounded-md border border-border-strong bg-surface px-3 py-2 font-mono text-text"
      />
      <ul
        id={listId}
        // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: a listbox is what this is.
        role="listbox"
        aria-labelledby={labelId}
        hidden={!expanded}
        className="max-h-64 overflow-y-auto rounded-md border border-border bg-surface py-1 shadow-lg"
      >
        {matches.map((unit) => {
          const retired = unit.status === "retired";
          const facts = [
            retired
              ? t("inventory.units.picker.retired")
              : t(`inventory.units.status.${unit.status}`),
            unit.serial,
            unit.mac,
          ].filter(Boolean);
          return (
            // biome-ignore lint/a11y/useKeyWithClickEvents: the combobox above handles the keys for every option.
            // biome-ignore lint/a11y/useFocusableInteractive: focus stays in the combobox, which points here with aria-activedescendant.
            <li
              key={unit.id}
              id={optionId(unit)}
              // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: an option of the listbox above.
              role="option"
              aria-selected={unit === active}
              aria-disabled={retired || undefined}
              // Keeps the focus in the box, so a click picks instead of blurring it first.
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => pick(unit)}
              className={`grid px-3 py-1.5 ${retired ? "cursor-not-allowed text-muted" : "cursor-pointer"} ${
                unit === active ? "bg-surface-2" : ""
              }`}
            >
              <span className="font-mono">{unit.code}</span>{" "}
              <span className="text-sm text-muted break-all">{facts.join(" · ")}</span>
            </li>
          );
        })}
      </ul>
      {/* The count is for screen readers, since the list shows it; "nothing found" is for all. */}
      <p role="status" className="text-sm text-muted">
        {status && (expanded ? <span className="sr-only">{status}</span> : status)}
      </p>
    </div>
  );
}

/**
 * The units whose code, serial or MAC holds TEXT, asked once typing pauses. Until then the
 * answer on hand is for older text, so `units` is undefined rather than a list that doesn't
 * match what is typed: Enter never picks a unit the owner didn't see offered for their text.
 */
function useUnitSuggestions(text: string) {
  const wanted = text.trim();
  const [settled, setSettled] = useState(wanted);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(wanted), PAUSE_MS);
    return () => clearTimeout(timer);
  }, [wanted]);

  const query = useQuery(unitSearchQuery(settled));
  const current = settled === wanted && wanted !== "";
  return {
    units: current ? query.data : undefined,
    isPending: wanted !== "" && (!current || query.isPending),
    isError: current && query.isError,
  };
}
