import type { QueryClient, QueryKey } from "@tanstack/react-query";

/**
 * Drops what a write made stale, and makes sure it is fetched again after the write.
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
  await Promise.all(
    queryKeys.map(async (queryKey) => {
      await queryClient.cancelQueries({ queryKey });
      await queryClient.invalidateQueries({ queryKey });
    }),
  );
}
