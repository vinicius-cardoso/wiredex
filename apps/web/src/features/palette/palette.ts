import { queryOptions, useQuery } from "@tanstack/react-query";
import type { SearchKind, SearchResults } from "@wiredex/api-client";
import { useEffect, useState } from "react";
import { api } from "../../shared/api/client";

/** How long typing pauses before the palette asks, as the part and unit pickers wait. */
const SEARCH_PAUSE_MS = 200;
/** The hits a kind shows: the API's default, said here so the request names it (19's 1.4). */
const HITS_PER_KIND = 5;
/** The longest text the search takes; the box stops there rather than earn a 422. */
export const MAX_SEARCH_LENGTH = 100;

/**
 * Every search hangs off one root, apart from the records' own: a hit is a pointer to a page,
 * and that page reads its record afresh, so nothing a write changes needs dropping here.
 */
export const paletteKeys = {
  all: ["palette"] as const,
  search: (text: string) => ["palette", "search", text] as const,
};

export function workspaceSearchQuery(text: string) {
  return queryOptions({
    queryKey: paletteKeys.search(text),
    queryFn: async (): Promise<SearchResults> => {
      const { data } = await api.GET("/api/search", {
        params: { query: { q: text, limit: HITS_PER_KIND } },
      });
      if (!data) throw new Error("Could not search the workspace");
      return data;
    },
    enabled: text !== "",
  });
}

/**
 * The workspace's records holding TEXT, grouped by kind (19's requirement 4.2), asked once typing
 * pauses. Until then the answer on hand is for older text, so `results` is undefined rather than
 * groups that don't match what is typed: Enter never opens a hit the owner didn't see offered.
 */
export function useWorkspaceSearch(text: string) {
  const wanted = text.trim();
  const [settled, setSettled] = useState(wanted);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(wanted), SEARCH_PAUSE_MS);
    return () => clearTimeout(timer);
  }, [wanted]);

  const query = useQuery(workspaceSearchQuery(settled));
  const current = settled === wanted && wanted !== "";
  return {
    results: current ? query.data : undefined,
    isPending: wanted !== "" && (!current || query.isPending),
    isError: current && query.isError,
  };
}

/** Each kind's group heading, in the reader's language. */
export function kindKey(kind: SearchKind) {
  return `palette.kind.${kind}` as const;
}
