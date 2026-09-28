import {
  type ChangeEvent,
  type KeyboardEvent,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { normalizeTag } from "./projects";

/** The server's own caps (requirement 2.2, 2.4), checked here so the box says so first. */
export const MAX_TAG_LENGTH = 32;
export const MAX_TAGS = 20;

const CONTROL = /\p{Cc}/u;

type Problem = "tooLong" | "control" | "tooMany";

type Props = {
  /** The visible label, which is also the text box's accessible name. */
  label: string;
  /** The tags chosen, each already normalized. */
  value: string[];
  onChange: (tags: string[]) => void;
  /** The workspace's tags, offered as the owner types (requirement 10.7). */
  suggestions?: string[];
  /** Ids of what describes the field, such as a problem the form shows under it. */
  describedBy?: string;
  invalid?: boolean;
};

/**
 * Tags as chips and a text box (requirement 10.7). Enter or a comma adds what was typed,
 * normalized as the server does, so a chip shows what will be stored; a pasted `a, b` adds
 * both. Backspace in an empty box removes the last chip, and each chip has its own remove
 * button. The workspace's tags not chosen yet are suggested in a listbox the arrows move
 * through, the WAI-ARIA combobox pattern the location picker uses: focus stays in the box.
 */
export function TagInput({
  label,
  value,
  onChange,
  suggestions = [],
  describedBy,
  invalid = false,
}: Props) {
  const { t } = useTranslation();
  const inputId = useId();
  const labelId = useId();
  const listId = useId();
  const problemId = useId();
  const input = useRef<HTMLInputElement>(null);

  const [draft, setDraft] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);

  const matches = useMemo(() => {
    if (!open) return [];
    const typed = normalizeTag(draft);
    return suggestions.filter((tag) => !value.includes(tag) && tag.includes(typed));
  }, [open, draft, suggestions, value]);
  const shown = active !== null && matches.includes(active) ? active : null;
  const optionId = (tag: string) => `${listId}-${matches.indexOf(tag)}`;
  const activeOptionId = shown === null ? undefined : optionId(shown);

  useEffect(() => {
    if (!activeOptionId) return;
    // jsdom has no scrollIntoView, hence the optional call.
    document.getElementById(activeOptionId)?.scrollIntoView?.({ block: "nearest" });
  }, [activeOptionId]);

  /** Adds each text as a tag, or says why one can't be; answers whether all went in. */
  function add(texts: string[], into: string[] = value): boolean {
    let next = into;
    for (const text of texts) {
      const tag = normalizeTag(text);
      if (tag === "" || next.includes(tag)) continue;
      const refused = refusalOf(tag, next.length);
      if (refused) {
        setProblem(refused);
        if (next !== into) onChange(next);
        return false;
      }
      next = [...next, tag];
    }
    setProblem(null);
    if (next !== into) onChange(next);
    return true;
  }

  function remove(tag: string) {
    onChange(value.filter((held) => held !== tag));
    setProblem(null);
    input.current?.focus();
  }

  function type(event: ChangeEvent<HTMLInputElement>) {
    // A comma ends a tag, whether typed or pasted; what follows the last one stays typed.
    const parts = event.target.value.split(",");
    const rest = parts.pop() ?? "";
    if (parts.length > 0 && !add(parts)) {
      setDraft(parts.join(","));
      return;
    }
    setDraft(rest);
    setOpen(true);
    setActive(null);
  }

  function step(by: 1 | -1) {
    if (matches.length === 0) return;
    const at = shown === null ? -1 : matches.indexOf(shown);
    const next =
      at === -1 ? (by === 1 ? 0 : matches.length - 1) : (at + by + matches.length) % matches.length;
    setActive(matches[next] ?? null);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) setOpen(true);
      else step(event.key === "ArrowDown" ? 1 : -1);
    } else if (event.key === "Enter") {
      if (shown !== null) {
        event.preventDefault();
        add([shown]);
        setDraft("");
        setActive(null);
      } else if (draft.trim() !== "") {
        // A typed tag is added, not the form submitted around it.
        event.preventDefault();
        if (add([draft])) setDraft("");
      }
    } else if (event.key === "Backspace" && draft === "" && value.length > 0) {
      event.preventDefault();
      onChange(value.slice(0, -1));
      setProblem(null);
    } else if (event.key === "Escape" && open && matches.length > 0) {
      // The first Escape shuts the list, so a dialog around the box stays open.
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
    }
  }

  const expanded = matches.length > 0;
  const described = [problem ? problemId : null, describedBy ?? null].filter(Boolean).join(" ");

  return (
    <div className="grid gap-1">
      <label id={labelId} htmlFor={inputId} className="text-sm font-medium">
        {label}
      </label>
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-border-strong bg-surface px-2 py-1.5">
        {value.length > 0 && (
          <ul aria-label={t("projects.tags.chosen")} className="flex flex-wrap gap-2">
            {value.map((tag) => (
              <li
                key={tag}
                className="flex items-center gap-1 rounded-full bg-surface-2 py-0.5 pr-1 pl-2.5 text-sm"
              >
                {tag}
                <button
                  type="button"
                  aria-label={t("projects.tags.remove", { tag })}
                  onClick={() => remove(tag)}
                  className="rounded-full px-1.5 text-muted hover:bg-border hover:text-text"
                >
                  <span aria-hidden="true">×</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="relative min-w-40 flex-1">
          <input
            ref={input}
            id={inputId}
            type="text"
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={expanded}
            aria-controls={listId}
            aria-activedescendant={activeOptionId}
            aria-describedby={described || undefined}
            aria-invalid={invalid || problem !== null || undefined}
            autoComplete="off"
            spellCheck={false}
            value={draft}
            placeholder={t("projects.tags.placeholder")}
            onChange={type}
            onKeyDown={onKeyDown}
            onBlur={() => setOpen(false)}
            className="w-full bg-transparent px-1 py-0.5 text-text outline-none"
          />
          <ul
            id={listId}
            // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: a listbox is what this is.
            role="listbox"
            aria-labelledby={labelId}
            hidden={!expanded}
            className="absolute inset-x-0 top-full z-10 mt-2 max-h-64 overflow-y-auto rounded-md border border-border bg-surface py-1 shadow-lg"
          >
            {matches.map((tag) => (
              // biome-ignore lint/a11y/useKeyWithClickEvents: the combobox above handles the keys for every option.
              // biome-ignore lint/a11y/useFocusableInteractive: focus stays in the combobox, which points here with aria-activedescendant.
              <li
                key={tag}
                id={optionId(tag)}
                // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: an option of the listbox above.
                role="option"
                aria-selected={tag === shown}
                // Keeps the focus in the box, so a click picks instead of blurring it first.
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  add([tag]);
                  setDraft("");
                  setActive(null);
                }}
                className={`cursor-pointer px-3 py-1.5 ${tag === shown ? "bg-surface-2" : ""}`}
              >
                {tag}
              </li>
            ))}
          </ul>
        </div>
      </div>
      <p className="text-sm text-muted">{t("projects.tags.hint")}</p>
      {problem && (
        <p id={problemId} role="alert" className="text-sm text-crit">
          {t(`projects.tags.error.${problem}`, {
            max: problem === "tooMany" ? MAX_TAGS : MAX_TAG_LENGTH,
          })}
        </p>
      )}
    </div>
  );
}

function refusalOf(tag: string, held: number): Problem | null {
  // Counted in code points, as the server counts characters, not in UTF-16 units.
  if ([...tag].length > MAX_TAG_LENGTH) return "tooLong";
  if (CONTROL.test(tag)) return "control";
  if (held >= MAX_TAGS) return "tooMany";
  return null;
}
