import { queryOptions, useQuery } from "@tanstack/react-query";
import type { HistoryPage, ShortRevisions, TiedUpParts } from "@wiredex/api-client";
import { api } from "../../shared/api/client";
import { historyKeys } from "../history/history";
import { bomKeys } from "../projects/bom/bom";
import { lifecycleKeys } from "../projects/build/lifecycle";

/** The newest changes the dashboard shows; the activity page has the rest (requirement 3.1). */
export const RECENT_CHANGES = 10;

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
};

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
    const { data } = await api.GET("/api/projects/holdings");
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
    const { data } = await api.GET("/api/projects/shortages");
    if (!data) throw new Error("Could not load the shortages");
    return data;
  },
});

/** The drafts whose BOM is short of parts, by project and label (requirement 2). */
export function useShortRevisions() {
  return useQuery(shortRevisionsQuery);
}
