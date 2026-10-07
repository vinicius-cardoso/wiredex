import type { QueryClient, QueryKey } from "@tanstack/react-query";

/**
 * The roots of what every write changes, whatever it wrote: each is one more change in the
 * history, and many add or remove a record the dashboard counts. They are named here, under the
 * features that own them, so that no write has to remember them.
 */
export const HISTORY_KEY = ["history"] as const;
export const DASHBOARD_KEY = ["dashboard"] as const;

/**
 * Drops what a write made stale, and makes sure it is fetched again after the write. The
 * history and the dashboard's counts go with every write, so a page that shows them is right
 * without being opened again: a part added from the dashboard is counted there at once.
 *
 * `invalidateQueries` alone isn't enough: a query still on its first load, with no data yet,
 * is not refetched but handed the request already in flight, which started before the write
 * and can't include it. A location added while the tree was still loading never appeared.
 * Cancelling first discards that request, so the refetch the invalidation starts is a new one.
 */
export async function refreshAfterWrite(
  queryClient: QueryClient,
  ...queryKeys: QueryKey[]
): Promise<void> {
  // Each root once, even when the write names one of the two itself.
  const roots = new Map(
    [...queryKeys, HISTORY_KEY, DASHBOARD_KEY].map((queryKey) => [
      JSON.stringify(queryKey),
      queryKey,
    ]),
  );
  await Promise.all(
    [...roots.values()].map(async (queryKey) => {
      await queryClient.cancelQueries({ queryKey });
      await queryClient.invalidateQueries({ queryKey });
    }),
  );
}
