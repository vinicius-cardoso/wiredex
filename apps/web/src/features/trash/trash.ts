import {
  infiniteQueryOptions,
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import type { TrashedItem, TrashKind, TrashPage } from "@wiredex/api-client";
import { api } from "../../shared/api/client";
import { refreshAfterWrite } from "../../shared/api/refresh";
import { trashKeys } from "./keys";
import { cachesOf, TRASH_KINDS } from "./kinds";

/** The trash's filters as the address holds them, each left out when it narrows nothing. */
export type TrashSearch = { kind?: TrashKind; q?: string };

/**
 * The address, read: a kind the API knows and a trimmed text, anything else dropped, so a
 * hand-edited link still opens the trash. A typed `?q=1` arrives as a number.
 */
export function validateTrashSearch(raw: Record<string, unknown>): TrashSearch {
  const search: TrashSearch = {};
  const kind = TRASH_KINDS.find((known) => known === raw.kind);
  if (kind) search.kind = kind;
  const given = typeof raw.q === "number" ? String(raw.q) : raw.q;
  const q = typeof given === "string" ? given.trim() : "";
  if (q) search.q = q;
  return search;
}

/**
 * The trash, newest first, a page of 50 at a time (requirements 4.1 to 4.3), narrowed by a
 * kind and a fragment of a name or detail, which the API matches. Each page asks for what
 * follows the last one's cursor, so a record restored or deleted meanwhile never shifts what
 * the next page holds. Every narrowing hangs under the trash's one root, which a write drops.
 */
export function trashQuery(search: TrashSearch = {}) {
  return infiniteQueryOptions({
    queryKey: [...trashKeys.all, search.kind ?? null, search.q ?? ""],
    queryFn: async ({ pageParam }): Promise<TrashPage> => {
      // null on the first page and for a filter not set: the client drops it from the query.
      const { data } = await api.GET("/api/trash", {
        params: { query: { cursor: pageParam, kind: search.kind ?? null, q: search.q ?? null } },
      });
      if (!data) throw new Error("Could not load the trash");
      return data;
    },
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    // A changed filter changes the key; the last rows stay until the new ones land.
    placeholderData: keepPreviousData,
  });
}

export function useTrash(search: TrashSearch = {}) {
  return useInfiniteQuery(trashQuery(search));
}

/**
 * What the page hears back from a write on one record. The hook's own callbacks rather than
 * ones passed to `mutate`: the refresh after the write takes the record's row off the list, and
 * a callback given to `mutate` is dropped once the row that called it is gone.
 */
export type TrashWriteCallbacks = {
  onDone?: (item: TrashedItem) => void;
  onFailed?: (item: TrashedItem) => void;
};

/**
 * Brings a record back as it was (requirement 9.4). Refused or not, the trash and the record's
 * caches are fetched again: a record restored or deleted for good elsewhere is a 404 here, and
 * the list should stop offering it.
 */
export function useRestoreFromTrash({ onDone, onFailed }: TrashWriteCallbacks = {}) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (item: TrashedItem): Promise<TrashedItem> => {
      const { response } = await api.POST("/api/trash/{kind}/{item_id}/restore", {
        params: { path: { kind: item.kind, item_id: item.id } },
      });
      if (!response.ok) throw new Error("Could not restore it");
      return item;
    },
    onSuccess: (item) => onDone?.(item),
    onError: (_error, item) => onFailed?.(item),
    onSettled: (_restored, _error, item) =>
      refreshAfterWrite(queryClient, trashKeys.all, ...cachesOf(item.kind)),
  });
}

/** Deletes a record in the trash for good, with what it holds (requirement 9.5). */
export function useDeleteForGood({ onDone, onFailed }: TrashWriteCallbacks = {}) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (item: TrashedItem): Promise<TrashedItem> => {
      const { response } = await api.DELETE("/api/trash/{kind}/{item_id}", {
        params: { path: { kind: item.kind, item_id: item.id } },
      });
      if (!response.ok) throw new Error("Could not delete it for good");
      return item;
    },
    onSuccess: (item) => onDone?.(item),
    onError: (_error, item) => onFailed?.(item),
    onSettled: (_deleted, _error, item) =>
      refreshAfterWrite(queryClient, trashKeys.all, ...cachesOf(item.kind)),
  });
}

/** Deletes everything in the trash for good (requirement 9.6), each kind's caches refreshed. */
export function useEmptyTrash(onEmptied?: () => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (): Promise<void> => {
      const { response } = await api.DELETE("/api/trash");
      if (!response.ok) throw new Error("Could not empty the trash");
    },
    onSuccess: () => onEmptied?.(),
    onSettled: () =>
      refreshAfterWrite(queryClient, trashKeys.all, ...TRASH_KINDS.flatMap(cachesOf)),
  });
}
