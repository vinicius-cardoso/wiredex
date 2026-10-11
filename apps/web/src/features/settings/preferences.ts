import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Preferences } from "@wiredex/api-client";
import { api } from "../../shared/api/client";
import { reorderKeys } from "../catalog/reorder";

export const preferencesQuery = queryOptions({
  queryKey: ["preferences"],
  queryFn: async (): Promise<Preferences> => {
    const { data } = await api.GET("/api/preferences");
    if (!data) throw new Error("Could not load the settings");
    return data;
  },
});

/** The workspace's settings; the defaults for one that never saved any. */
export function usePreferences() {
  return useQuery(preferencesQuery);
}

/**
 * Saves the settings whole. What they change is read again: the reorder list is compared by
 * the stock basis chosen here.
 */
export function useUpdatePreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (preferences: Preferences): Promise<Preferences> => {
      const { data } = await api.PUT("/api/preferences", { body: preferences });
      if (!data) throw new Error("Could not save the settings");
      return data;
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(preferencesQuery.queryKey, saved);
      return queryClient.invalidateQueries({ queryKey: reorderKeys.all });
    },
  });
}
