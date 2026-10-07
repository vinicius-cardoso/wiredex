import { preferences } from "../../shared/lib/storage";
import type { BenchCounts } from "../dashboard/dashboard";

/** A page a mission is done on. */
export type MissionPath =
  | "/locations"
  | "/categories"
  | "/parts/new"
  | "/projects/new"
  | "/firmware/new"
  | "/units";

/**
 * A first thing to do on the bench. It ticks itself: `count` names the record the bench must
 * hold one of, and a mission without one is ticked by what the reader did here (opening the
 * palette). `to` is where it is done; without one, *Show me* points at `target` instead.
 */
export type Mission = {
  id: "location" | "category" | "part" | "project" | "firmware" | "board" | "palette";
  count?: keyof BenchCounts;
  to?: MissionPath;
  target?: string;
};

/** In the order a new bench is filled: somewhere to keep things, then what is kept and built. */
export const MISSIONS: readonly Mission[] = [
  { id: "location", count: "locations", to: "/locations" },
  // A part is filed under a category, so the category comes before it.
  { id: "category", count: "categories", to: "/categories" },
  { id: "part", count: "parts", to: "/parts/new" },
  { id: "project", count: "projects", to: "/projects/new" },
  { id: "firmware", count: "firmware", to: "/firmware/new" },
  { id: "board", count: "boards", to: "/units" },
  { id: "palette", target: '[data-tour="search"]' },
];

/** Which missions are done, from what the bench holds and what was done on this device. */
export function missionsDone(
  counts: BenchCounts | undefined,
  marked: readonly string[],
): ReadonlySet<Mission["id"]> {
  const done = MISSIONS.filter((mission) =>
    mission.count ? (counts?.[mission.count] ?? 0) > 0 : marked.includes(mission.id),
  );
  return new Set(done.map((mission) => mission.id));
}

/** A stop of the look-around: what it points at, or nothing for a card in the middle. */
export type Stop = { id: StopId; target?: string };

export type StopId =
  | "welcome"
  | "parts"
  | "locations"
  | "boards"
  | "projects"
  | "firmware"
  | "activity"
  | "search"
  | "quickAdd"
  | "account"
  | "palette";

export const STOPS: readonly Stop[] = [
  { id: "welcome" },
  { id: "parts", target: '[data-tour="nav-parts"]' },
  { id: "locations", target: '[data-tour="nav-locations"]' },
  { id: "boards", target: '[data-tour="nav-units"]' },
  { id: "projects", target: '[data-tour="nav-projects"]' },
  { id: "firmware", target: '[data-tour="nav-firmware"]' },
  { id: "activity", target: '[data-tour="nav-activity"]' },
  { id: "search", target: '[data-tour="search"]' },
  { id: "quickAdd", target: '[data-tour="quick-add"]' },
  { id: "account", target: '[data-tour="account"]' },
];

/** A module's page that has a tour of its own. */
export type TourPage =
  | "parts"
  | "categories"
  | "locations"
  | "units"
  | "projects"
  | "firmware"
  | "activity"
  | "trash";

/** What a page tour points at. Each is an anchor the shared page components carry. */
export type PageAnchor = "actions" | "filters" | "pages" | "list" | "tree" | "detail";

export const PAGE_ANCHORS: Record<PageAnchor, string> = {
  actions: '[data-tour="page-actions"]',
  filters: '[data-tour="filters"]',
  pages: '[data-tour="pages"]',
  list: '[data-tour="list"]',
  tree: '[data-tour="tree"]',
  detail: '[data-tour="detail"]',
};

/**
 * Each page's stops, in the order the eye meets them. A stop whose anchor isn't on screen is
 * left out when the tour starts: the bar of pages of an empty list, the filters a phone folds.
 */
export const PAGE_TOURS: Record<TourPage, { path: string; stops: readonly PageAnchor[] }> = {
  parts: { path: "/parts", stops: ["actions", "filters", "pages", "list"] },
  categories: { path: "/categories", stops: ["actions", "tree", "detail"] },
  locations: { path: "/locations", stops: ["actions", "tree", "detail"] },
  units: { path: "/units", stops: ["filters", "pages", "list"] },
  projects: { path: "/projects", stops: ["actions", "filters", "pages", "list"] },
  firmware: { path: "/firmware", stops: ["actions", "filters", "pages", "list"] },
  activity: { path: "/activity", stops: ["filters", "pages", "list"] },
  trash: { path: "/trash", stops: ["filters", "pages", "list"] },
};

/** The page with a tour at this address, a trailing slash aside; null for any other. */
export function tourPageAt(pathname: string): TourPage | null {
  const path = pathname.replace(/\/+$/, "") || "/";
  const found = Object.entries(PAGE_TOURS).find(([, tour]) => tour.path === path);
  return found ? (found[0] as TourPage) : null;
}

/** What the tour remembers on this device; nothing of it is on the server. */
export type TourMemory = {
  /** The dashboard's offer was answered, either way. */
  offered: boolean;
  /** The missions are on screen. */
  missions: boolean;
  /** The missions ticked by what was done here, not by what the bench holds. */
  marked: string[];
};

export const NO_MEMORY: TourMemory = { offered: false, missions: false, marked: [] };

const KEY = "wiredex.tour";

/** Reads what is remembered; storage that is blocked or holds nonsense remembers nothing. */
export function readMemory(): TourMemory {
  try {
    const stored: unknown = JSON.parse(preferences.read(KEY) ?? "null");
    if (!stored || typeof stored !== "object") return NO_MEMORY;
    const memory = stored as Partial<TourMemory>;
    return {
      offered: memory.offered === true,
      missions: memory.missions === true,
      marked: Array.isArray(memory.marked)
        ? memory.marked.filter((id): id is string => typeof id === "string")
        : [],
    };
  } catch {
    return NO_MEMORY;
  }
}

export function writeMemory(memory: TourMemory): void {
  preferences.write(KEY, JSON.stringify(memory));
}
