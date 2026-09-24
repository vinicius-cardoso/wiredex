import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UserInfo } from "@wiredex/api-client";
import { api } from "../../shared/api/client";

/** Who is logged in, or null for nobody. A 401 is an answer here, not an error. */
export const currentUserQuery = queryOptions({
  queryKey: ["auth", "me"],
  queryFn: async (): Promise<UserInfo | null> => {
    const { data, response } = await api.GET("/api/auth/me");
    if (response.status === 401) return null;
    if (!data) throw new Error("Could not check who is logged in");
    return data;
  },
  staleTime: 5 * 60_000,
});

export function useCurrentUser() {
  return useQuery(currentUserQuery);
}

export type LoginFailure = "credentials" | "throttled" | "unavailable";

export class LoginError extends Error {
  constructor(readonly reason: LoginFailure) {
    super(`login failed: ${reason}`);
  }
}

const failures: Partial<Record<number, LoginFailure>> = { 401: "credentials", 429: "throttled" };

export type Credentials = { email: string; password: string };

export function useLogIn() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (credentials: Credentials): Promise<UserInfo> => {
      const { data, response } = await api.POST("/api/auth/login", { body: credentials });
      if (data) return data;
      throw new LoginError(failures[response.status] ?? "unavailable");
    },
    onSuccess: (user) => queryClient.setQueryData(currentUserQuery.queryKey, user),
  });
}

/** Why a login failed, in words the page can show. A network error is "unavailable". */
export function loginFailure(error: unknown): LoginFailure {
  return error instanceof LoginError ? error.reason : "unavailable";
}

export function useLogOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.POST("/api/auth/logout");
    },
    // Whatever the server answered, this tab forgets the user and what it loaded for them.
    onSettled: () => forgetUser(queryClient),
  });
}

export function forgetUser(queryClient: ReturnType<typeof useQueryClient>) {
  // The user query is set to null in place, not removed: removing it wouldn't tell the
  // components watching it, and they would keep showing the old user.
  queryClient.setQueryData(currentUserQuery.queryKey, null);
  queryClient.removeQueries({
    predicate: ({ queryKey }) => queryKey[0] !== "system" && queryKey[0] !== "auth",
  });
}
