import { queryOptions, useQuery } from "@tanstack/react-query";
import type { Netlist } from "@wiredex/api-client";
import { api } from "../../../shared/api/client";
import { detailOf } from "../projects";

/**
 * Every netlist hangs off one root, apart from the projects root: a net write drops its own
 * revision's netlist, and a BOM write or a transition drops it too, since both change what a
 * reference resolves to or whether the netlist can change (spec 11, requirement 10.10).
 */
export const netlistKeys = {
  all: ["netlist"] as const,
  revision: (revisionId: string) => ["netlist", "revision", revisionId] as const,
};

export function netlistQuery(revisionId: string) {
  return queryOptions({
    queryKey: netlistKeys.revision(revisionId),
    queryFn: async (): Promise<Netlist> => {
      const { data, error } = await api.GET("/api/projects/revisions/{revision_id}/netlist", {
        params: { path: { revision_id: revisionId } },
      });
      if (data) return data;
      throw new Error(detailOf(error));
    },
  });
}

/**
 * A revision's nets, what each reference resolves to and what the editor picks from. The
 * resolutions are computed by the API at every read (requirement 4.3), so the query is simply
 * fetched again whenever something they depend on may have moved.
 */
export function useNetlist(revisionId: string) {
  return useQuery(netlistQuery(revisionId));
}
