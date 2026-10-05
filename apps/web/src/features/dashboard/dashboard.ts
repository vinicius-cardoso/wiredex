import { queryOptions, useQuery } from "@tanstack/react-query";
import type { HistoryPage, ShortRevisions, TiedUpParts } from "@wiredex/api-client";
import { api } from "../../shared/api/client";
import { historyKeys } from "../history/history";
import { bomKeys } from "../projects/bom/bom";
import { lifecycleKeys } from "../projects/build/lifecycle";

/** The newest changes the dashboard shows; the activity page has the rest (requirement 3.1). */
export const RECENT_CHANGES = 5;

/** How many rows a panel asks for; the API answers how many more there are. */
export const PANEL_ROWS = 5;

/**
 * Each panel's cache hangs off the root its data moves with (design decision 5): the parts tied
 * up in builds off the lifecycle's, which every transition drops; the shortages off the BOMs',
 * which a transition, a quick add and an import drop; the recent activity off history's, which a
 * restore drops. Like every query in the app they are stale as soon as they land, so whatever
 * changed elsewhere shows the next time the dashboard opens (requirement 5.3).
 */
export const dashboardKeys = {
  recentActivity: [...historyKeys.all, "recent"] as const,
  tiedUpParts: [...lifecycleKeys.all, "tied-up"] as const,
  shortRevisions: [...bomKeys.all, "short-drafts"] as const,
  counts: ["dashboard", "counts"] as const,
};

/** How much the bench holds of each kind of record, for the tiles above the panels. */
export type BenchCounts = {
  parts: number;
  boards: number;
  projects: number;
  firmware: number;
  locations: number;
};

export const benchCountsQuery = queryOptions({
  queryKey: dashboardKeys.counts,
  // The paged lists answer their total with any page, so one row is asked of each.
  queryFn: async (): Promise<BenchCounts> => {
    const one = { params: { query: { page_size: 1 } } };
    const [parts, boards, projects, firmware, locations] = await Promise.all([
      api.GET("/api/catalog/parts", one),
      api.GET("/api/inventory/units", one),
      api.GET("/api/projects"),
      api.GET("/api/firmware"),
      api.GET("/api/inventory/locations"),
    ]);
    if (!parts.data || !boards.data || !projects.data || !firmware.data || !locations.data)
      throw new Error("Could not count the bench");
    return {
      parts: parts.data.total,
      boards: boards.data.total,
      projects: projects.data.length,
      firmware: firmware.data.length,
      locations: locations.data.length,
    };
  },
});

/** The bench's counts; like the panels, read again each time the dashboard opens. */
export function useBenchCounts() {
  return useQuery(benchCountsQuery);
}

export const recentActivityQuery = queryOptions({
  queryKey: dashboardKeys.recentActivity,
  queryFn: async (): Promise<HistoryPage> => {
    const { data } = await api.GET("/api/history", {
      params: { query: { page_size: RECENT_CHANGES } },
    });
    if (!data) throw new Error("Could not load the recent activity");
    return data;
  },
});

/** The workspace's newest changes, as 17's feed answers them. */
export function useRecentActivity() {
  return useQuery(recentActivityQuery);
}

export const tiedUpPartsQuery = queryOptions({
  queryKey: dashboardKeys.tiedUpParts,
  queryFn: async (): Promise<TiedUpParts> => {
    const { data } = await api.GET("/api/projects/holdings", {
      params: { query: { limit: PANEL_ROWS } },
    });
    if (!data) throw new Error("Could not load the parts tied up in builds");
    return data;
  },
});

/** The parts reserved and built revisions hold, the most tied up first (requirement 1). */
export function useTiedUpParts() {
  return useQuery(tiedUpPartsQuery);
}

export const shortRevisionsQuery = queryOptions({
  queryKey: dashboardKeys.shortRevisions,
  queryFn: async (): Promise<ShortRevisions> => {
    const { data } = await api.GET("/api/projects/shortages", {
      params: { query: { limit: PANEL_ROWS } },
    });
    if (!data) throw new Error("Could not load the shortages");
    return data;
  },
});

/** The drafts whose BOM is short of parts, by project and label (requirement 2). */
export function useShortRevisions() {
  return useQuery(shortRevisionsQuery);
}
