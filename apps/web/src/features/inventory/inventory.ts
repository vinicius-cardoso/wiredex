import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { LocationChange, LocationNode, NewLocation } from "@wiredex/api-client";
import { api } from "../../shared/api/client";

/**
 * Every inventory cache hangs off one root key, so a change that ripples through the tree —
 * a location added, moved, deleted — is one invalidation of `all`.
 */
export const inventoryKeys = {
  all: ["inventory"] as const,
  locations: ["inventory", "locations"] as const,
};

export const locationsQuery = queryOptions({
  queryKey: inventoryKeys.locations,
  queryFn: async (): Promise<LocationNode[]> => {
    const { data } = await api.GET("/api/inventory/locations");
    if (!data) throw new Error("Could not load the locations");
    return data;
  },
});

export function useLocations() {
  return useQuery(locationsQuery);
}

/** A location with the branch below it, which is how the tree is drawn. */
export type LocationBranch = { location: LocationNode; children: LocationBranch[] };

/**
 * The flat list the API answers with, turned into the tree it describes. Children keep the
 * order they arrived in, and a location whose parent isn't in the list is drawn as a root
 * rather than dropped.
 */
export function locationTree(locations: LocationNode[]): LocationBranch[] {
  const branches = new Map(
    locations.map((location): [string, LocationBranch] => [
      location.id,
      { location, children: [] },
    ]),
  );
  const roots: LocationBranch[] = [];
  for (const branch of branches.values()) {
    const parent =
      branch.location.parent_id === null ? undefined : branches.get(branch.location.parent_id);
    if (parent) parent.children.push(branch);
    else roots.push(branch);
  }
  return roots;
}

/**
 * A refusal from the API, with the status and the message it gave. The message says which of
 * children or lots blocks a delete, so the page shows it in place (requirement 9.2).
 */
export class InventoryRefusal extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail || `the inventory refused this with ${status}`);
  }
}

/** What the API said, whether it answered a plain message or a list of field errors. */
export function detailOf(error: unknown): string {
  const detail = (error as { detail?: unknown } | null | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((entry) => String((entry as { msg?: unknown }).msg ?? ""))
      .filter(Boolean)
      .join("; ");
  }
  return "";
}

/** What the API said it refused, in its own words, for showing next to the control. */
export function refusalMessage(error: unknown): string | null {
  return error instanceof InventoryRefusal && error.detail ? error.detail : null;
}

/**
 * One invalidation for every inventory change. A location touches its own row and the counts
 * on the tree, so the cheap and correct move is to drop the lot.
 */
function useInventoryInvalidation() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: inventoryKeys.all });
}

export function useCreateLocation() {
  const invalidate = useInventoryInvalidation();
  return useMutation({
    mutationFn: async (body: NewLocation): Promise<void> => {
      const { data, error, response } = await api.POST("/api/inventory/locations", { body });
      if (!data) throw new InventoryRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export type LocationEdit = { locationId: string; body: LocationChange };

/** A rename, a move, or both: whatever the body carries (requirements 1.5 to 1.8). */
export function useEditLocation() {
  const invalidate = useInventoryInvalidation();
  return useMutation({
    mutationFn: async ({ locationId, body }: LocationEdit): Promise<void> => {
      const { data, error, response } = await api.PATCH("/api/inventory/locations/{location_id}", {
        params: { path: { location_id: locationId } },
        body,
      });
      if (!data) throw new InventoryRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export function useDeleteLocation() {
  const invalidate = useInventoryInvalidation();
  return useMutation({
    mutationFn: async (locationId: string): Promise<void> => {
      const { error, response } = await api.DELETE("/api/inventory/locations/{location_id}", {
        params: { path: { location_id: locationId } },
      });
      // 409 lands here with the message saying what still hangs off it (requirement 9.2).
      if (!response.ok && response.status !== 404) {
        throw new InventoryRefusal(response.status, detailOf(error));
      }
    },
    onSuccess: invalidate,
  });
}
