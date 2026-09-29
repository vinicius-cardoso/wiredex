import type { SearchResult } from "@wiredex/api-client";
import { type ChangeEvent, type KeyboardEvent, type Ref, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { usePartSuggestions } from "./search/search";

/** A picked part: its id, and the name the box shows while it is picked. */
export type PickedPart = { id: string; name: string };

export type PartPickerProps = {
  /** The label, which is also the combobox's accessible name. */
  label: string;
  /** Shows the label to screen readers only, where a column header already says it. */
  labelHidden?: boolean;
  /** The picked part, or null while none is picked. */
  value: PickedPart | null;
  /** Gets the part picked, or null when the box is emptied. */
  onChange: (part: PickedPart | null) => void;
  /** Ids of what describes the field, such as a problem shown under it. */
  describedBy?: string;
  /** Marks the field as refused, beside a problem that says why. */
  invalid?: boolean;
  /** The text box, so a row can put focus on it. */
  ref?: Ref<HTMLInputElement>;
};

/**
 * Picks a part by typing part of its name, manufacturer or part number (09's requirement
 * 11.4), over catalog's search once typing pauses. In `features/catalog` because the BOM
 * editor picks parts now and 11's netlist editor will too.
 *
 * It is the WAI-ARIA combobox with a list popup and manual selection, as `LocationPicker` is.
 * Typing opens the suggestions, each with its part number and manufacturer; the arrows move
 * through them, Enter picks the one moved to, and Escape shuts the list. While the list is shut
 * the box shows the picked part's name: leaving it, or Escape, drops a draft that wasn't
 * picked. Enter and Escape only reach the row around it while the list is shut, so Enter picks
 * first and adds the line second, and the first Escape shuts the list rather than the row.
 *
 * The list sits in the flow under the box instead of floating over the page: pickers live in
 * tables that scroll sideways on a phone, whose box would clip a popup.
 */
export function PartPicker({
  label,
  labelHidden = false,
  value,
  onChange,
  describedBy,
  invalid = false,
  ref,
}: PartPickerProps) {
  const { t } = useTranslation();
  const inputId = useId();
  const labelId = useId();
  const listId = useId();

  const pickedText = value?.name ?? "";
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const suggestions = usePartSuggestions(open ? draft : "");

  const text = open ? draft : pickedText;
  const matches = open ? (suggestions.parts ?? []) : [];
  const active = matches.find((part) => part.id === activeId);
  const expanded = matches.length > 0;
  const optionId = (part: SearchResult) => `${listId}-${part.id}`;
  const activeOptionId = active ? optionId(active) : undefined;

  useEffect(() => {
    if (!activeOptionId) return;
    // jsdom has no scrollIntoView, hence the optional call.
    document.getElementById(activeOptionId)?.scrollIntoView?.({ block: "nearest" });
  }, [activeOptionId]);

  function pick(part: SearchResult) {
    onChange({ id: part.id, name: part.name });
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
    const at = matches.findIndex((part) => part.id === activeId);
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
        // Opens on the picked part's name, so its neighbours can be reached from the keys.
        setDraft(pickedText);
        setOpen(true);
      }
    } else if (event.key === "Enter" && open) {
      // Nothing picked yet, so Enter picks rather than adds the line, even when it finds nothing.
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
    if (suggestions.isError) status = t("catalog.picker.error");
    else if (suggestions.isPending) status = t("catalog.picker.loading");
    else if (matches.length === 0) status = t("catalog.picker.none");
    else status = t("catalog.picker.count", { count: matches.length });
  }

  return (
    <div className="grid gap-1">
      <label
        id={labelId}
        htmlFor={inputId}
        className={labelHidden ? "sr-only" : "text-sm font-medium"}
      >
        {label}
      </label>
      <input
        ref={ref}
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
        placeholder={t("catalog.picker.placeholder")}
        onChange={type}
        onKeyDown={onKeyDown}
        onBlur={() => setOpen(false)}
        className="w-full min-w-40 rounded-md border border-border-strong bg-surface px-2 py-1.5 text-text"
      />
      <ul
        id={listId}
        // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: a listbox is what this is.
        role="listbox"
        aria-labelledby={labelId}
        hidden={!expanded}
        className="max-h-64 overflow-y-auto rounded-md border border-border bg-surface py-1 shadow-lg"
      >
        {matches.map((part) => (
          // biome-ignore lint/a11y/useKeyWithClickEvents: the combobox above handles the keys for every option.
          // biome-ignore lint/a11y/useFocusableInteractive: focus stays in the combobox, which points here with aria-activedescendant.
          <li
            key={part.id}
            id={optionId(part)}
            // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: an option of the listbox above.
            role="option"
            aria-selected={part === active}
            // Keeps the focus in the box, so a click picks instead of blurring it first.
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => pick(part)}
            className={`grid cursor-pointer px-3 py-1.5 ${part === active ? "bg-surface-2" : ""}`}
          >
            <span>{part.name}</span>{" "}
            {(part.mpn || part.manufacturer) && (
              <span className="text-sm text-muted">
                {[part.mpn, part.manufacturer].filter(Boolean).join(" · ")}
              </span>
            )}
          </li>
        ))}
      </ul>
      {/* The count is for screen readers, since the list shows it; "nothing found" is for all. */}
      <p role="status" className="text-sm text-muted">
        {status && (expanded ? <span className="sr-only">{status}</span> : status)}
      </p>
    </div>
  );
}
