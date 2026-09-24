import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { SessionInfo } from "@wiredex/api-client";
import { api } from "../../shared/api/client";
import { forgetUser } from "../auth/auth";

export const sessionsQuery = queryOptions({
  queryKey: ["account", "sessions"],
  queryFn: async (): Promise<SessionInfo[]> => {
    const { data } = await api.GET("/api/auth/sessions");
    if (!data) throw new Error("Could not load the sessions");
    return data;
  },
});

export function useSessions() {
  return useQuery(sessionsQuery);
}

/** Logs one device out. For the current device, that's logging out here too. */
export function useRevokeSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (session: SessionInfo): Promise<SessionInfo> => {
      const { response } = await api.DELETE("/api/auth/sessions/{session_id}", {
        params: { path: { session_id: session.id } },
      });
      // 404: already gone, which is what was asked for.
      if (!response.ok && response.status !== 404) throw new Error("Could not log it out");
      return session;
    },
    onSuccess: (session) => {
      if (session.current) forgetUser(queryClient);
      else void queryClient.invalidateQueries({ queryKey: sessionsQuery.queryKey });
    },
  });
}
