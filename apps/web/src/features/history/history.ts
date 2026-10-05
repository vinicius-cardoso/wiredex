import {
  keepPreviousData,
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type {
  HistoryAction,
  HistoryChange,
  HistoryPage,
  HistoryRecordKind,
} from "@wiredex/api-client";
import { api } from "../../shared/api/client";
import { refreshAfterWrite } from "../../shared/api/refresh";
import {
  DEFAULT_PAGE_SIZE,
  type PageSearch,
  pageOfSearch,
  validatePageSearch,
} from "../../shared/ui/pagination";
import { detailOf } from "../catalog/catalog";
import { trashKeys } from "../trash/keys";
import { cachesOf } from "../trash/kinds";

/** The kinds of record with a timeline of their own: those with a page (decision 12). */
export type TimelineKind = "part" | "unit" | "project" | "firmware";

/** What a change can do to its record, in the order the activity's filter offers them. */
export const HISTORY_ACTIONS: readonly HistoryAction[] = [
  "created",
  "edited",
  "moved_to_trash",
  "restored_from_trash",
  "restored_version",
  "deleted",
];

/** The kinds of record a change can be about, in the order the activity's filter offers them. */
export const RECORD_KINDS: readonly HistoryRecordKind[] = [
  "part",
  "unit",
  "project",
  "firmware",
  "category",
  "location",
];

/**
 * The activity's filters and page as the address holds them, each left out when it narrows
 * nothing or is the default.
 */
export type ActivitySearch = PageSearch & {
  action?: HistoryAction;
  kind?: HistoryRecordKind;
  q?: string;
};

/**
 * The address, read: an action and a kind the API knows, a trimmed text and a page, anything
 * else dropped, so a hand-edited link still opens the activity. A typed `?q=7` arrives as a
 * number.
 */
export function validateActivitySearch(raw: Record<string, unknown>): ActivitySearch {
  const search: ActivitySearch = validatePageSearch(raw);
  const action = HISTORY_ACTIONS.find((known) => known === raw.action);
  if (action) search.action = action;
  const kind = RECORD_KINDS.find((known) => known === raw.kind);
  if (kind) search.kind = kind;
  const given = typeof raw.q === "number" ? String(raw.q) : raw.q;
  const q = typeof given === "string" ? given.trim() : "";
  if (q) search.q = q;
  return search;
}

/**
 * Every history cache hangs off one root: a restore adds a change to the feed and to its
 * record's timeline at once, so it drops them all, whatever the feed was narrowed by.
 */
export const historyKeys = {
  all: ["history"] as const,
  feed: (search: ActivitySearch = {}, page = 1, size: number = DEFAULT_PAGE_SIZE) =>
    [
      "history",
      "feed",
      search.action ?? null,
      search.kind ?? null,
      search.q ?? "",
      page,
      size,
    ] as const,
  timeline: (kind: TimelineKind, recordId: string, page = 1, size: number = DEFAULT_PAGE_SIZE) =>
    ["history", "timeline", kind, recordId, page, size] as const,
};

/**
 * A page of the workspace's changes, newest first, 50 unless asked (requirement 2), narrowed by
 * what each did, the kind of its record and a fragment of the record's name, which the API
 * matches. A page past the end is answered as the last one, and `page` says which.
 */
export function activityQuery(search: ActivitySearch = {}) {
  const { page, size } = pageOfSearch(search);
  return queryOptions({
    queryKey: historyKeys.feed(search, page, size),
    queryFn: async (): Promise<HistoryPage> => {
      // null for a filter not set: the client drops it from the query.
      const { data } = await api.GET("/api/history", {
        params: {
          query: {
            page,
            page_size: size,
            action: search.action ?? null,
            kind: search.kind ?? null,
            q: search.q ?? null,
          },
        },
      });
      if (!data) throw new Error("Could not load the activity");
      return data;
    },
    // A new page or filter changes the key; the last blocks stay until the new ones land.
    placeholderData: keepPreviousData,
  });
}

export function useActivity(search: ActivitySearch = {}) {
  return useQuery(activityQuery(search));
}

/**
 * A page of one record's changes, newest first (requirement 3), asked for only once its
 * section is opened (decision 12): `enabled` is that.
 */
export function useTimeline(
  kind: TimelineKind,
  recordId: string,
  enabled: boolean,
  page = 1,
  size: number = DEFAULT_PAGE_SIZE,
) {
  return useQuery({
    queryKey: historyKeys.timeline(kind, recordId, page, size),
    queryFn: async (): Promise<HistoryPage> => {
      const { data } = await api.GET("/api/history/{kind}/{record_id}", {
        params: { path: { kind, record_id: recordId }, query: { page, page_size: size } },
      });
      if (!data) throw new Error("Could not load the history");
      return data;
    },
    // The page before stays on screen while the next one loads, but never another record's.
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[3] === recordId ? previous : undefined,
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
