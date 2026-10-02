import {
  infiniteQueryOptions,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import type { HistoryChange, HistoryPage } from "@wiredex/api-client";
import { api } from "../../shared/api/client";
import { refreshAfterWrite } from "../../shared/api/refresh";
import { detailOf } from "../catalog/catalog";
import { trashKeys } from "../trash/keys";
import { cachesOf } from "../trash/kinds";

/** The kinds of record with a timeline of their own: those with a page (decision 12). */
export type TimelineKind = "part" | "unit" | "project" | "firmware";

/**
 * Every history cache hangs off one root: a restore adds a change to the feed and to its
 * record's timeline at once, so it drops them all.
 */
export const historyKeys = {
  all: ["history"] as const,
  feed: ["history", "feed"] as const,
  timeline: (kind: TimelineKind, recordId: string) =>
    ["history", "timeline", kind, recordId] as const,
};

/** The workspace's changes, newest first, 50 at a time (requirement 2). */
export const activityQuery = infiniteQueryOptions({
  queryKey: historyKeys.feed,
  queryFn: async ({ pageParam }): Promise<HistoryPage> => {
    // null on the first page: the client drops it from the query string.
    const { data } = await api.GET("/api/history", { params: { query: { cursor: pageParam } } });
    if (!data) throw new Error("Could not load the activity");
    return data;
  },
  initialPageParam: null as string | null,
  getNextPageParam: (page) => page.next_cursor,
});

export function useActivity() {
  return useInfiniteQuery(activityQuery);
}

/**
 * One record's changes, newest first (requirement 3), asked for only once its section is
 * opened (decision 12): `enabled` is that.
 */
export function useTimeline(kind: TimelineKind, recordId: string, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: historyKeys.timeline(kind, recordId),
    queryFn: async ({ pageParam }): Promise<HistoryPage> => {
      const { data } = await api.GET("/api/history/{kind}/{record_id}", {
        params: { path: { kind, record_id: recordId }, query: { cursor: pageParam } },
      });
      if (!data) throw new Error("Could not load the history");
      return data;
    },
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled,
  });
}

/** Why a restore didn't happen, in the API's words: the record's module says what it refused. */
export class RestoreRefusal extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail || `the restore was refused with ${status}`);
  }
}

/**
 * Puts a change's record back as it was before it (requirement 4). The record's own caches, the
 * trash a restore may take it out of and history are fetched again, refused or not: a 409 can
 * mean the record moved on since the page was read.
 */
export function useRestoreVersion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (change: HistoryChange): Promise<void> => {
      const { error, response } = await api.POST("/api/history/changes/{change_id}/restore", {
        params: { path: { change_id: change.id } },
      });
      if (!response.ok) throw new RestoreRefusal(response.status, detailOf(error));
    },
    onSettled: (_restored, _error, change) =>
      refreshAfterWrite(
        queryClient,
        historyKeys.all,
        trashKeys.all,
        ...(isTimelineKind(change.record.kind) ? cachesOf(change.record.kind) : []),
      ),
  });
}

export function isTimelineKind(kind: string): kind is TimelineKind {
  return kind === "part" || kind === "unit" || kind === "project" || kind === "firmware";
}
