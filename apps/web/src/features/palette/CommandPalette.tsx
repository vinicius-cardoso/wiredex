import { useNavigate } from "@tanstack/react-router";
import type { SearchHit, SearchKind } from "@wiredex/api-client";
import { type ChangeEvent, type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuickAdd } from "../inventory/intake/QuickAddProvider";
import { type Command, commandKey, matchingCommands } from "./commands";
import { kindKey, MAX_SEARCH_LENGTH, useWorkspaceSearch } from "./palette";

type Props = {
  /** Closes the palette; `after` runs once it is gone and focus is back. */
  onClose: (after?: () => void) => void;
};

type Choice =
  | { id: string; command: Command; hit?: never; kind?: never }
  | { id: string; hit: SearchHit; kind: SearchKind; command?: never };

type Group = { id: string; title: string; more: boolean; choices: Choice[] };

/**
 * The palette (19-command-palette): one search box and one list of choices, the commands
 * matching what is typed first, then, once typing pauses, the records the workspace holds, a
 * group per kind (requirement 4.2).
 *
 * It is the WAI-ARIA combobox with a list popup, as the pickers are (requirement 5.2): focus
 * stays in the box, the arrows move the active choice through every group in order, wrapping
 * around, and Enter opens it; with nothing moved to, the first choice is the one Enter takes
 * (4.3). Escape and the backdrop close it (3.4). A status line says when the search is asked,
 * fails or finds nothing, and tells assistive technology how many choices there are (4.6).
 */
export function CommandPalette({ onClose }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const quickAdd = useQuickAdd();
  const headingId = useId();
  const listId = useId();
  const box = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const search = useWorkspaceSearch(text);

  const commands = matchingCommands(text, (command) => t(commandKey(command.id)));
  const groups: Group[] = [
    ...(commands.length > 0
      ? [
          {
            id: "commands",
            title: t("palette.commands"),
            more: false,
            choices: commands.map((command) => ({ id: `command-${command.id}`, command })),
          },
        ]
      : []),
    ...(search.results?.groups ?? []).map((group) => ({
      id: group.kind,
      title: t(kindKey(group.kind)),
      more: group.more,
      choices: group.hits.map((hit) => ({ id: `${group.kind}-${hit.id}`, hit, kind: group.kind })),
    })),
  ];
  const choices = groups.flatMap((group) => group.choices);
  const active = choices.find((choice) => choice.id === activeId) ?? choices[0];
  const optionId = (choice: Choice) => `${listId}-${choice.id}`;
  const activeOptionId = active ? optionId(active) : undefined;

  useEffect(() => {
    box.current?.focus();
  }, []);

  useEffect(() => {
    if (!activeOptionId) return;
    // jsdom has no scrollIntoView, hence the optional call.
    document.getElementById(activeOptionId)?.scrollIntoView?.({ block: "nearest" });
  }, [activeOptionId]);

  function choose(choice: Choice) {
    if (choice.command) {
      const { command } = choice;
      if (command.to === null) onClose(() => quickAdd.open());
      else onClose(() => void navigate({ to: command.to }));
      return;
    }
    const id = choice.hit.id;
    switch (choice.kind) {
      case "part":
        onClose(() => void navigate({ to: "/parts/$partId", params: { partId: id } }));
        break;
      case "unit":
        onClose(() => void navigate({ to: "/units/$unitId", params: { unitId: id } }));
        break;
      case "project":
        onClose(() => void navigate({ to: "/projects/$projectId", params: { projectId: id } }));
        break;
      case "firmware":
        onClose(() => void navigate({ to: "/firmware/$firmwareId", params: { firmwareId: id } }));
        break;
      case "category":
        // A category has no page of its own: its parts are where it is used (decision 8).
        onClose(() => void navigate({ to: "/parts", search: { category: id } }));
        break;
      case "location":
        onClose(() => void navigate({ to: "/locations", search: { selected: id } }));
        break;
    }
  }

  function type(event: ChangeEvent<HTMLInputElement>) {
    setText(event.target.value);
    setActiveId(null);
  }

  function step(by: 1 | -1) {
    if (choices.length === 0) return;
    const at = active ? choices.indexOf(active) : -1;
    const next = (at + by + choices.length) % choices.length;
    setActiveId(choices[next]?.id ?? null);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      step(event.key === "ArrowDown" ? 1 : -1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (active) choose(active);
    } else if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    }
  }

  const wanted = text.trim();
  let status = t("palette.count", { count: choices.length });
  let shown = false;
  if (search.isError) {
    status = t("palette.error");
    shown = true;
  } else if (search.isPending) {
    status = t("palette.searching");
    shown = true;
  } else if (wanted !== "" && choices.length === 0) {
    status = t("palette.none", { text: wanted });
    shown = true;
  }

  return (
    <div className="fixed inset-0 z-50 grid overflow-y-auto p-4">
      <button
        type="button"
        aria-label={t("palette.close")}
        onClick={() => onClose()}
        className="fixed inset-0 -z-10 cursor-default bg-black/40"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        className="mx-auto mt-[8vh] grid w-full min-w-0 max-w-xl content-start gap-2 self-start rounded-lg border border-border bg-surface p-3 shadow-lg"
      >
        <h2 id={headingId} className="sr-only">
          {t("palette.title")}
        </h2>
        <input
          ref={box}
          type="text"
          role="combobox"
          aria-label={t("palette.label")}
          aria-autocomplete="list"
          aria-expanded={choices.length > 0}
          aria-controls={listId}
          aria-activedescendant={activeOptionId}
          autoComplete="off"
          spellCheck={false}
          maxLength={MAX_SEARCH_LENGTH}
          value={text}
          placeholder={t("palette.placeholder")}
          onChange={type}
          onKeyDown={onKeyDown}
          className="w-full min-w-0 rounded-md border border-border-strong bg-surface px-3 py-2 text-text"
        />
        <ul
          id={listId}
          // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: a listbox is what this is.
          role="listbox"
          aria-label={t("palette.choices")}
          hidden={choices.length === 0}
          className="grid max-h-[60vh] min-w-0 gap-1 overflow-y-auto"
        >
          {groups.map((group) => (
            <GroupOf
              key={group.id}
              group={group}
              active={active}
              optionId={optionId}
              onChoose={choose}
            />
          ))}
        </ul>
        <p role="status" className="px-1 text-sm text-muted">
          {shown ? status : <span className="sr-only">{status}</span>}
        </p>
      </div>
    </div>
  );
}

type GroupProps = {
  group: Group;
  active: Choice | undefined;
  optionId: (choice: Choice) => string;
  onChoose: (choice: Choice) => void;
};

/** One group of the list, named by its heading, which says when more of its kind match (4.5). */
function GroupOf({ group, active, optionId, onChoose }: GroupProps) {
  const { t } = useTranslation();
  const headingId = useId();

  return (
    <li role="presentation" className="grid min-w-0">
      {/* biome-ignore lint/a11y/useSemanticElements: a listbox's group of options, which a fieldset can't be. */}
      <ul role="group" aria-labelledby={headingId} className="grid min-w-0">
        <li
          role="presentation"
          id={headingId}
          className="px-3 pt-2 pb-1 text-xs font-semibold tracking-wide text-muted uppercase"
        >
          {group.title}
          {/* The space is its own text node, so the group's name reads "Parts · more match". */}
          {group.more && (
            <>
              {" "}
              <span className="font-normal normal-case">· {t("palette.more")}</span>
            </>
          )}
        </li>
        {group.choices.map((choice) => {
          const selected = choice === active;
          const title = choice.command ? t(commandKey(choice.command.id)) : choice.hit.title;
          const detail = choice.hit?.detail ?? null;
          return (
            // biome-ignore lint/a11y/useKeyWithClickEvents: the combobox above handles the keys for every option.
            // biome-ignore lint/a11y/useFocusableInteractive: focus stays in the combobox, which points here with aria-activedescendant.
            <li
              key={choice.id}
              id={optionId(choice)}
              // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: an option of the listbox above.
              role="option"
              aria-selected={selected}
              // Keeps the focus in the box, so a click opens the choice instead of blurring it.
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => onChoose(choice)}
              className={`grid min-w-0 cursor-pointer rounded-md px-3 py-1.5 ${
                selected ? "bg-surface-2" : "hover:bg-surface-2"
              }`}
            >
              <span className="font-medium wrap-anywhere">{title}</span>
              {/* A space of its own, so the option's name reads "title detail"; the grid drops it. */}
              {detail && (
                <>
                  {" "}
                  <span className="text-sm text-muted wrap-anywhere">{detail}</span>
                </>
              )}
            </li>
          );
        })}
      </ul>
    </li>
  );
}
