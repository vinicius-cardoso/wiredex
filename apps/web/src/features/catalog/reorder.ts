import { queryOptions, useQuery } from "@tanstack/react-query";
import type { ReorderList } from "@wiredex/api-client";
import { api } from "../../shared/api/client";

/**
 * Apart from the catalog's own root: the list also moves with stock and with reservations,
 * so every stock write and every settings change drops it, by this key.
 */
export const reorderKeys = { all: ["reorder"] as const };

export const reorderQuery = queryOptions({
  queryKey: reorderKeys.all,
  queryFn: async (): Promise<ReorderList> => {
    const { data } = await api.GET("/api/catalog/reorder");
    if (!data) throw new Error("Could not load the reorder list");
    return data;
  },
  // Stock moves from many pages; a list a minute old is still read again when it is opened.
  staleTime: 0,
});

/** The parts below their minimum stock, the emptiest first (spec 24). */
export function useReorderList() {
  return useQuery(reorderQuery);
}
