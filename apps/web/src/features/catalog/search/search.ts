import {
  infiniteQueryOptions,
  keepPreviousData,
  queryOptions,
  useInfiniteQuery,
  useQuery,
} from "@tanstack/react-query";
import type { FacetsResponse, PartSearchResponse } from "@wiredex/api-client";
import { api } from "../../../shared/api/client";
import { catalogKeys } from "../catalog";
import type { PartQuery } from "./searchParams";
import { requestFromQuery } from "./searchParams";

/**
 * The search hooks: the parts a search matches, page by page, and the facet counts for a
 * category. Both are TanStack Query, so the address stays the one source of truth and the
 * cache does the rest (web conventions).
 */

export const searchKeys = {
  parts: (query: PartQuery) =>
    [...catalogKeys.all, "search", "parts", requestFromQuery(query)] as const,
  facets: (categoryId: string, text: string, pin: string) =>
    [...catalogKeys.all, "search", "facets", categoryId, text.trim(), pin.trim()] as const,
};

/**
 * One search, its pages continued by the opaque cursor. The cursor rides in the body, not
 * the query string, since a filter list is structured data (design's Web); each page sends
 * the same search with the previous page's `next_cursor` (requirement 4.3).
 */
export function partSearchQuery(query: PartQuery) {
  return infiniteQueryOptions({
    queryKey: searchKeys.parts(query),
    queryFn: async ({ pageParam }): Promise<PartSearchResponse> => {
      const body = { ...requestFromQuery(query), cursor: pageParam };
      const { data } = await api.POST("/api/catalog/parts/search", { body });
      if (!data) throw new Error("Could not search the parts");
      return data;
    },
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    // A changed filter changes the key; the last rows stay until the new ones land, so the
    // table doesn't blink empty between keystrokes.
    placeholderData: keepPreviousData,
  });
}

export function usePartSearch(query: PartQuery) {
  return useInfiniteQuery(partSearchQuery(query));
}

/**
 * A category's facets over text and pin only: the attribute filters don't narrow them, so
 * every option stays selectable as the owner picks (requirement 5.2). Skipped until a
 * category is chosen, since there is no schema, and so no facets, before that.
 */
export function facetsQuery(categoryId: string, text: string, pin: string) {
  return queryOptions({
    queryKey: searchKeys.facets(categoryId, text, pin),
    queryFn: async (): Promise<FacetsResponse> => {
      const query = { q: text.trim() || null, pin: pin.trim() || null };
      const { data } = await api.GET("/api/catalog/categories/{category_id}/facets", {
        params: { path: { category_id: categoryId }, query },
      });
      if (!data) throw new Error("Could not load the facets");
      return data;
    },
  });
}

export function useFacets(categoryId: string | null, text: string, pin: string) {
  return useQuery({
    ...facetsQuery(categoryId ?? "", text, pin),
    enabled: categoryId !== null && categoryId !== "",
  });
}
