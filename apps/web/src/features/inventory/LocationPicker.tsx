import type { LocationNode } from "@wiredex/api-client";
import {
  type ChangeEvent,
  type KeyboardEvent,
  type Ref,
  useEffect,
  useId,
  useMemo,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { locationPath, matchesLocation, useLocations } from "./inventory";
import { control } from "./StockDialog";

/** A location as the picker offers it: with the path it is shown and searched by. */
type Choice = { location: LocationNode; path: string };

export type LocationPickerProps = {
  /** The visible label, which is also the combobox's accessible name. */
  label: string;
  /** The picked location's id, or null while none is picked. */
  value: string | null;
  /** Gets the location picked, or null when the box is emptied. */
  onChange: (locationId: string | null) => void;
  /** Ids of what describes the field, such as a problem shown under it. */
  describedBy?: string;
  /** Marks the field as refused, beside a problem that says why. */
  invalid?: boolean;
  /** The text box, so a form can put focus on it. */
  ref?: Ref<HTMLInputElement>;
};

/**
 * Picks a location by typing part of its name, its path or its short code (requirements 9.2,
 * 9.3), over the tree `useLocations` has already loaded.
 *
 * It is the WAI-ARIA combobox with a list popup and manual selection. Typing opens the list of
 * matches, each shown with its path and code; the arrows move through them, Enter picks the
 * one moved to, or the location whose code is exactly the text, and Escape shuts the list.
 * While the list is shut the box shows the picked location's path, so what it says is what is
 * picked: leaving it, or Escape, drops a draft that wasn't picked. Emptying it lets the picked
 * location go. Enter only reaches an enclosing form while the list is shut, and Escape only
 * reaches an enclosing dialog then, so the first Escape shuts the list and the second the
 * dialog.
 */
export function LocationPicker({
  label,
  value,
  onChange,
  describedBy,
  invalid = false,
  ref,
}: LocationPickerProps) {
  const { t } = useTranslation();
  const inputId = useId();
  const labelId = useId();
  const listId = useId();
  const locations = useLocations();

  const choices = useMemo((): Choice[] => {
    const all = locations.data ?? [];
    return all.map((location) => ({ location, path: locationPath(location, all) }));
  }, [locations.data]);

  const pickedText = choices.find((choice) => choice.location.id === value)?.path ?? "";
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);

  const text = open ? draft : pickedText;
  const matches = open ? matching(choices, draft) : [];
  const active = matches.find((choice) => choice.location.id === activeId);
  const expanded = matches.length > 0;
  const optionId = (choice: Choice) => `${listId}-${choice.location.id}`;
  const activeOptionId = active ? optionId(active) : undefined;

  useEffect(() => {
    if (!activeOptionId) return;
    // jsdom has no scrollIntoView, hence the optional call.
    document.getElementById(activeOptionId)?.scrollIntoView?.({ block: "nearest" });
  }, [activeOptionId]);

  function pick(choice: Choice) {
    onChange(choice.location.id);
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

  /** Opens the list on the text as it stands, at its first or last match. */
  function openAt(edge: "first" | "last") {
    const shown = matching(choices, pickedText);
    setDraft(pickedText);
    setOpen(true);
    setActiveId((edge === "first" ? shown[0] : shown.at(-1))?.location.id ?? null);
  }

  function step(by: 1 | -1) {
    if (matches.length === 0) return;
    const at = matches.findIndex((choice) => choice.location.id === activeId);
    const next =
      at === -1 ? (by === 1 ? 0 : matches.length - 1) : (at + by + matches.length) % matches.length;
    setActiveId(matches[next]?.location.id ?? null);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const by = event.key === "ArrowDown" ? 1 : -1;
      if (open) step(by);
      else openAt(by === 1 ? "first" : "last");
    } else if (event.key === "Enter" && open) {
      // Nothing picked yet, so Enter picks rather than submits, even when it finds nothing.
      event.preventDefault();
      const choice = active ?? exactCode(matches, draft);
      if (choice) pick(choice);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
    }
  }

  let status = "";
  if (open && locations.isPending) status = t("inventory.locations.loading");
  else if (open && locations.isError) status = t("inventory.locations.error");
  else if (open && matches.length === 0) status = t("inventory.picker.none");
  else if (open) status = t("inventory.picker.count", { count: matches.length });

  return (
    <div className="grid gap-1">
      <label id={labelId} htmlFor={inputId} className="text-sm font-medium">
        {label}
      </label>
      <div className="relative">
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
          placeholder={t("inventory.picker.placeholder")}
          onChange={type}
          onKeyDown={onKeyDown}
          onBlur={() => setOpen(false)}
          className={`${control} w-full`}
        />
        <ul
          id={listId}
          // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: a listbox is what this is.
          role="listbox"
          aria-labelledby={labelId}
          hidden={!expanded}
          className="absolute inset-x-0 top-full z-10 mt-1 max-h-64 overflow-y-auto rounded-md border border-border bg-surface py-1 shadow-lg"
        >
          {matches.map((choice) => (
            // biome-ignore lint/a11y/useKeyWithClickEvents: the combobox above handles the keys for every option.
            // biome-ignore lint/a11y/useFocusableInteractive: focus stays in the combobox, which points here with aria-activedescendant.
            <li
              key={choice.location.id}
              id={optionId(choice)}
              // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: an option of the listbox above.
              role="option"
              aria-selected={choice === active}
              // Keeps the focus in the box, so a click picks instead of blurring it first.
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => pick(choice)}
              className={`flex cursor-pointer items-baseline justify-between gap-3 px-3 py-1.5 ${
                choice === active ? "bg-surface-2" : ""
              }`}
            >
              <span>{choice.path}</span>{" "}
              <span className="font-mono text-sm text-muted">{choice.location.code}</span>
            </li>
          ))}
        </ul>
      </div>
      {/* The count is for screen readers, since the list shows it; "nothing found" is for all. */}
      <p role="status" className="text-sm text-muted">
        {status && (expanded ? <span className="sr-only">{status}</span> : status)}
      </p>
    </div>
  );
}

function matching(choices: Choice[], text: string): Choice[] {
  return choices.filter((choice) => matchesLocation(choice.location, text, choice.path));
}

/** The location whose short code the text is, in any case (requirement 9.3). */
function exactCode(choices: Choice[], text: string): Choice | undefined {
  const code = text.trim().toUpperCase();
  return choices.find((choice) => choice.location.code.toUpperCase() === code);
}
