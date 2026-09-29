import {
  infiniteQueryOptions,
  keepPreviousData,
  queryOptions,
  useInfiniteQuery,
  useQuery,
} from "@tanstack/react-query";
import type { FacetsResponse, PartSearchResponse, SearchResult } from "@wiredex/api-client";
import { useEffect, useState } from "react";
import { api } from "../../../shared/api/client";
import { CatalogRefusal, catalogKeys, detailOf } from "../catalog";
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
  suggestions: (text: string) => [...catalogKeys.all, "search", "suggestions", text] as const,
};

/** How many parts a picker offers, and how long typing pauses before it asks for them. */
export const SUGGESTION_LIMIT = 8;
export const SUGGESTION_PAUSE_MS = 200;

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
      const { data, error, response } = await api.POST("/api/catalog/parts/search", { body });
      // A 422 names the filter it refused; the page shows it next to that filter (6.5).
      if (data) return data;
      throw new CatalogRefusal(response.status, detailOf(error));
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

export function partSuggestionsQuery(text: string) {
  return queryOptions({
    queryKey: searchKeys.suggestions(text),
    queryFn: async (): Promise<SearchResult[]> => {
      const body = {
        text,
        exact_category: false,
        sort: "name",
        direction: "asc",
        limit: SUGGESTION_LIMIT,
      };
      const { data, error, response } = await api.POST("/api/catalog/parts/search", { body });
      if (data) return data.items;
      throw new CatalogRefusal(response.status, detailOf(error));
    },
  });
}

/**
 * The parts whose name, manufacturer or part number holds TEXT, for a picker (09's
 * requirement 11.4); the search also matches the package, which only adds suggestions.
 *
 * It asks once typing pauses, not on every key. Until then the answer on hand is for older
 * text, so `parts` is undefined rather than a list that doesn't match what is typed: Enter
 * never picks a part the owner didn't see offered for their text.
 */
export function usePartSuggestions(text: string) {
  const wanted = text.trim();
  const [settled, setSettled] = useState(wanted);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(wanted), SUGGESTION_PAUSE_MS);
    return () => clearTimeout(timer);
  }, [wanted]);

  const query = useQuery({ ...partSuggestionsQuery(settled), enabled: settled !== "" });
  const current = settled === wanted && wanted !== "";
  return {
    parts: current ? query.data : undefined,
    isPending: wanted !== "" && (!current || query.isPending),
    isError: current && query.isError,
  };
}
