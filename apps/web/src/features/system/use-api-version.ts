import { useQuery } from "@tanstack/react-query";
import type { VersionInfo } from "@wiredex/api-client";
import { api } from "../../shared/api/client";

export function useApiVersion() {
  return useQuery({
    queryKey: ["system", "version"],
    queryFn: async (): Promise<VersionInfo> => {
      const { data, error } = await api.GET("/api/version");
      if (error || !data) throw new Error("The API did not report its version");
      return data;
    },
    // Refetched when the tab regains focus, so a tab left open across a deploy notices.
    staleTime: 60_000,
  });
}
