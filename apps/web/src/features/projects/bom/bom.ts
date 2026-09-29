import { queryOptions, useQuery } from "@tanstack/react-query";
import type { Bom } from "@wiredex/api-client";
import { api } from "../../../shared/api/client";
import { detailOf } from "../projects";

/**
 * Every BOM hangs off one root, apart from the projects root: a line write drops its own
 * revision's BOM, and a quick-add or an import drops them all, since a new part or new stock
 * can change any report (requirement 11.14).
 */
export const bomKeys = {
  all: ["bom"] as const,
  revision: (revisionId: string) => ["bom", "revision", revisionId] as const,
};

export function bomQuery(revisionId: string) {
  return queryOptions({
    queryKey: bomKeys.revision(revisionId),
    queryFn: async (): Promise<Bom> => {
      const { data, error, response } = await api.GET("/api/projects/revisions/{revision_id}/bom", {
        params: { path: { revision_id: revisionId } },
      });
      if (data) return data;
      throw new BomRefusal(response.status, detailOf(error));
    },
  });
}

/**
 * A revision's lines, its shortage report and whether it can change. The report is computed
 * by the API at every read (requirement 6.7), so the query is simply fetched again whenever
 * something it depends on may have moved.
 */
export function useBom(revisionId: string) {
  return useQuery(bomQuery(revisionId));
}

/** A refusal from the BOM routes, with the status and the message the API gave. */
export class BomRefusal extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail || `the BOM API refused this with ${status}`);
  }
}
