/** A page a command opens: every page of the navigation, the devices, and the "new" pages. */
export type CommandPath =
  | "/"
  | "/parts"
  | "/categories"
  | "/locations"
  | "/units"
  | "/projects"
  | "/firmware"
  | "/activity"
  | "/trash"
  | "/sessions"
  | "/parts/new"
  | "/projects/new"
  | "/firmware/new"
  | "/import";

/** A choice that opens a page, or quick-add, without naming a record (19's requirement 4.1). */
export type Command =
  | { id: Exclude<CommandId, "quickAdd" | "tour">; to: CommandPath }
  | { id: "quickAdd" | "tour"; to: null };

export type CommandId =
  | "dashboard"
  | "parts"
  | "categories"
  | "locations"
  | "units"
  | "projects"
  | "firmware"
  | "activity"
  | "trash"
  | "sessions"
  | "newPart"
  | "newProject"
  | "newFirmware"
  | "import"
  | "quickAdd"
  | "tour";

/**
 * Every command, in the order the palette lists them: the navigation's pages in its order, the
 * devices, then the pages that start something, quick-add and the tour (decision 10 of requirements). A
 * fixed list, filtered in the browser: they are few and need no request.
 */
export const COMMANDS: readonly Command[] = [
  { id: "dashboard", to: "/" },
  { id: "parts", to: "/parts" },
  { id: "categories", to: "/categories" },
  { id: "locations", to: "/locations" },
  { id: "units", to: "/units" },
  { id: "projects", to: "/projects" },
  { id: "firmware", to: "/firmware" },
  { id: "activity", to: "/activity" },
  { id: "trash", to: "/trash" },
  { id: "sessions", to: "/sessions" },
  { id: "newPart", to: "/parts/new" },
  { id: "newProject", to: "/projects/new" },
  { id: "newFirmware", to: "/firmware/new" },
  { id: "import", to: "/import" },
  { id: "quickAdd", to: null },
  { id: "tour", to: null },
];

export function commandKey(id: CommandId) {
  return `palette.command.${id}` as const;
}

/**
 * The commands whose name, in the reader's language, holds the text, case aside, in their own
 * order (19's requirement 4.2). A blank text keeps them all (4.1).
 */
export function matchingCommands(text: string, nameOf: (command: Command) => string): Command[] {
  const wanted = text.trim().toLocaleLowerCase();
  if (!wanted) return [...COMMANDS];
  return COMMANDS.filter((command) => nameOf(command).toLocaleLowerCase().includes(wanted));
}
