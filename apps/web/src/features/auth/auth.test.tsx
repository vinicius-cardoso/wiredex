import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import {
  acceptLogins,
  acceptLogout,
  OWNER,
  respondAsLoggedIn,
  respondAsLoggedOut,
} from "../../test/server";
import { currentUserQuery, loginFailure, useCurrentUser, useLogIn, useLogOut } from "./auth";

function wrapper(queryClient: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function setup<T>(hook: () => T) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { queryClient, ...renderHook(hook, { wrapper: wrapper(queryClient) }) };
}

describe("useCurrentUser", () => {
  it("is the logged-in user", async () => {
    respondAsLoggedIn();
    const { result } = setup(useCurrentUser);

    await waitFor(() => expect(result.current.data).toEqual(OWNER));
  });

  it("is null, not an error, when nobody is logged in", async () => {
    respondAsLoggedOut();
    const { result } = setup(useCurrentUser);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeNull();
  });
});

describe("useLogIn", () => {
  it("remembers the user it logged in", async () => {
    acceptLogins();
    const { result, queryClient } = setup(useLogIn);

    await act(() =>
      result.current.mutateAsync({ email: OWNER.email, password: "correct horse battery" }),
    );

    expect(queryClient.getQueryData(currentUserQuery.queryKey)).toEqual(OWNER);
  });

  it.each([
    [200, "wrong password", "credentials"],
    [429, "correct horse battery", "throttled"],
    [503, "correct horse battery", "unavailable"],
  ] as const)("reports a %i as %s", async (status, password, reason) => {
    acceptLogins({ status });
    const { result } = setup(useLogIn);

    await act(async () => {
      await result.current.mutateAsync({ email: OWNER.email, password }).catch(() => {});
    });

    expect(loginFailure(result.current.error)).toBe(reason);
  });
});

describe("useLogOut", () => {
  it("forgets the user and what was loaded for them, but keeps system data", async () => {
    acceptLogout();
    const { result, queryClient } = setup(useLogOut);
    queryClient.setQueryData(currentUserQuery.queryKey, OWNER);
    queryClient.setQueryData(["sessions"], []);
    queryClient.setQueryData(["system", "version"], { version: "1.0.0" });

    await act(() => result.current.mutateAsync());

    expect(queryClient.getQueryData(currentUserQuery.queryKey)).toBeNull();
    expect(queryClient.getQueryData(["sessions"])).toBeUndefined();
    expect(queryClient.getQueryData(["system", "version"])).toEqual({ version: "1.0.0" });
  });
});
