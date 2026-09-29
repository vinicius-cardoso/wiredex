import { queryOptions, useQuery } from "@tanstack/react-query";
import type { PinUsage } from "@wiredex/api-client";
import { api } from "../../../shared/api/client";
import { detailOf } from "../projects";

/**
 * Every part's pin usage hangs off one root, so a net write, a BOM write, a pinout save or a
 * transition drops them all: any of them can change what a pin of any part is on (spec 12,
 * requirement 10.7).
 */
export const pinUsageKeys = {
  all: ["pinUsage"] as const,
  part: (partId: string) => ["pinUsage", "part", partId] as const,
};

/** What is wired to each pin of a part, across every revision of the bench (requirement 7). */
export function usePinUsage(partId: string) {
  return useQuery(
    queryOptions({
      queryKey: pinUsageKeys.part(partId),
      queryFn: async (): Promise<PinUsage> => {
        const { data, error } = await api.GET("/api/projects/parts/{part_id}/pin-usage", {
          params: { path: { part_id: partId } },
        });
        if (data) return data;
        throw new Error(detailOf(error));
      },
    }),
  );
}
