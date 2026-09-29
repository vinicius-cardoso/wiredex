import type { Netlist } from "@wiredex/api-client";
import {
  type ChangeEvent,
  type KeyboardEvent,
  type Ref,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { replaceToken, type Suggestion, suggestionsFor, tokenAt } from "./pinList";

type Props = {
  label: string;
  value: string;
  onChange: (text: string) => void;
  netlist: Netlist | undefined;
  describedBy?: string | undefined;
  invalid?: boolean | undefined;
  ref?: Ref<HTMLInputElement>;
};

/**
 * The pins of a net, typed as `U1.25, U2.SDA, R1.2`, with the BOM's designators and then their
 * parts' pins offered for the item under the caret (spec 11, decision 14, requirement 10.4).
 *
 * The WAI-ARIA combobox with a list popup and manual selection, as the part picker is: the
 * arrows move through the suggestions, Enter picks the one moved to, and Escape shuts the list.
 * Picking a designator writes `U1.` and offers its pins; picking a pin writes its number. Enter
 * and Escape reach the row only while the list is shut or nothing is picked, so Enter adds the
 * net once the pins are typed. The list sits in the flow, not over the page, for a table that
 * scrolls sideways on a phone.
 */
export function PinListInput({
  label,
  value,
  onChange,
  netlist,
  describedBy,
  invalid,
  ref,
}: Props) {
  const { t } = useTranslation();
  const inputId = useId();
  const labelId = useId();
  const listId = useId();
  const input = useRef<HTMLInputElement | null>(null);
  const [caret, setCaret] = useState(value.length);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  // Where a pick leaves the caret: set once React has written the new value, before the next
  // key can arrive, so typing after a pick goes where the pick ended.
  const placeCaret = useRef<number | null>(null);

  useLayoutEffect(() => {
    if (placeCaret.current === null) return;
    input.current?.setSelectionRange(placeCaret.current, placeCaret.current);
    placeCaret.current = null;
  });

  const token = tokenAt(value, caret);
  const suggestions: Suggestion[] = open && token.text ? suggestionsFor(token.text, netlist) : [];
  const expanded = suggestions.length > 0;
  const optionId = (index: number) => `${listId}-${index}`;
  const activeOptionId = active >= 0 && active < suggestions.length ? optionId(active) : undefined;

  useEffect(() => {
    if (!activeOptionId) return;
    document.getElementById(activeOptionId)?.scrollIntoView?.({ block: "nearest" });
  }, [activeOptionId]);

  function setRefs(element: HTMLInputElement | null) {
    input.current = element;
    if (typeof ref === "function") ref(element);
    else if (ref) (ref as { current: HTMLInputElement | null }).current = element;
  }

  function type(event: ChangeEvent<HTMLInputElement>) {
    onChange(event.target.value);
    setCaret(event.target.selectionStart ?? event.target.value.length);
    setOpen(true);
    setActive(-1);
  }

  function pick(suggestion: Suggestion) {
    const [next, at] = replaceToken(value, token, suggestion.value);
    onChange(next);
    setCaret(at);
    setActive(-1);
    setOpen(!suggestion.final);
    placeCaret.current = at;
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if ((event.key === "ArrowDown" || event.key === "ArrowUp") && expanded) {
      event.preventDefault();
      const by = event.key === "ArrowDown" ? 1 : -1;
      const last = suggestions.length - 1;
      setActive((at) => (at === -1 ? (by === 1 ? 0 : last) : (at + by + last + 1) % (last + 1)));
    } else if (event.key === "Enter" && expanded && activeOptionId) {
      event.preventDefault();
      const chosen = suggestions[active];
      if (chosen) pick(chosen);
    } else if (event.key === "Escape" && expanded) {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
    }
  }

  const status = expanded
    ? t("projects.netlist.editor.suggestions", { count: suggestions.length })
    : "";

  return (
    <div className="grid gap-1">
      <label id={labelId} htmlFor={inputId} className="sr-only">
        {label}
      </label>
      <input
        ref={setRefs}
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
        value={value}
        placeholder={t("projects.netlist.editor.pinsPlaceholder")}
        onChange={type}
        onKeyDown={onKeyDown}
        onSelect={(event) => setCaret(event.currentTarget.selectionStart ?? value.length)}
        onBlur={() => setOpen(false)}
        className="w-full min-w-48 rounded-md border border-border-strong bg-surface px-2 py-1.5 font-mono text-text"
      />
      <ul
        id={listId}
        // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: a listbox is what this is.
        role="listbox"
        aria-labelledby={labelId}
        hidden={!expanded}
        className="max-h-64 overflow-y-auto rounded-md border border-border bg-surface py-1 shadow-lg"
      >
        {suggestions.map((suggestion, index) => (
          // biome-ignore lint/a11y/useKeyWithClickEvents: the combobox above handles the keys for every option.
          // biome-ignore lint/a11y/useFocusableInteractive: focus stays in the combobox, which points here with aria-activedescendant.
          <li
            key={suggestion.value}
            id={optionId(index)}
            // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: an option of the listbox above.
            role="option"
            aria-selected={index === active}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => pick(suggestion)}
            className={`flex cursor-pointer gap-2 px-3 py-1.5 ${index === active ? "bg-surface-2" : ""}`}
          >
            <span className="font-mono">{suggestion.primary}</span>
            {suggestion.secondary && (
              <span className="text-sm text-muted">{suggestion.secondary}</span>
            )}
          </li>
        ))}
      </ul>
      <p role="status" className="sr-only">
        {status}
      </p>
    </div>
  );
}
