import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  AdjustRequest,
  BalanceResponse,
  LocationChange,
  LocationNode,
  MoveRequest,
  MoveResponse,
  NewLocation,
  PartStock,
  PartTotal,
  ReceiveRequest,
} from "@wiredex/api-client";
import { api } from "../../shared/api/client";
import { refreshAfterWrite } from "../../shared/api/refresh";
import { catalogKeys } from "../catalog/catalog";

/**
 * Every inventory cache hangs off one root key, so a change that ripples through the tree —
 * a location added, moved, deleted — is one invalidation of `all`.
 */
export const inventoryKeys = {
  all: ["inventory"] as const,
  locations: ["inventory", "locations"] as const,
  partStock: (partId: string) => ["inventory", "part-stock", partId] as const,
  partTotals: (partIds: readonly string[]) => ["inventory", "part-totals", partIds] as const,
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
 * The names from the root down to a location, as in `Lab / Cabinet A / Drawer 3`. A parent
 * missing from the list ends the path where it is, the way `locationTree` draws such a location
 * as a root, and a loop in the parents can't make it run forever.
 */
export function locationPath(location: LocationNode, all: readonly LocationNode[]): string {
  const byId = new Map(all.map((node): [string, LocationNode] => [node.id, node]));
  const names = [location.name];
  const seen = new Set([location.id]);
  let parent = location.parent_id === null ? undefined : byId.get(location.parent_id);
  while (parent && !seen.has(parent.id)) {
    names.unshift(parent.name);
    seen.add(parent.id);
    parent = parent.parent_id === null ? undefined : byId.get(parent.parent_id);
  }
  return names.join(" / ");
}

/**
 * Whether a location's name or short code, or its path when one is given, contains the text
 * (requirements 9.1, 9.2). The Locations page matches names and codes, since the tree already
 * shows each match's place; the picker passes the path, so `lab / dra` finds `Drawer 3`. Blank
 * text matches everything.
 */
export function matchesLocation(location: LocationNode, text: string, path?: string): boolean {
  const wanted = foldForSearch(text);
  if (wanted === "") return true;
  return [location.name, location.code, path]
    .filter((field): field is string => field !== undefined)
    .some((field) => foldForSearch(field).includes(wanted));
}

/**
 * Text as a search compares it: case, accents and runs of spaces don't count, nor does the
 * spacing around a `/`, so `lab/drawer` is `Lab / Drawer`. It is how the server folds a
 * location's path when a sheet names one (design decision 8).
 */
function foldForSearch(text: string): string {
  return text
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .replace(/ ?\/ ?/g, "/")
    .trim();
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
  return () => refreshAfterWrite(queryClient, inventoryKeys.all);
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

/** One part's total and its per-location breakdown, for the part page (requirement 7.3). */
export function partStockQuery(partId: string) {
  return queryOptions({
    queryKey: inventoryKeys.partStock(partId),
    queryFn: async (): Promise<PartStock> => {
      const { data } = await api.GET("/api/inventory/parts/{part_id}/stock", {
        params: { path: { part_id: partId } },
      });
      if (!data) throw new Error("Could not load the stock");
      return data;
    },
  });
}

export function usePartStock(partId: string) {
  return useQuery(partStockQuery(partId));
}

/**
 * The totals for a page of parts, in one query (requirement 7.2). A part with no stock is
 * simply absent from the answer, so the caller reads a missing id as zero. Skipped when the
 * page is empty: there is nothing to ask about, and an empty `part_id` list is a bad request.
 */
export function partTotalsQuery(partIds: readonly string[]) {
  return queryOptions({
    queryKey: inventoryKeys.partTotals(partIds),
    queryFn: async (): Promise<Map<string, number>> => {
      const { data } = await api.GET("/api/inventory/parts/stock", {
        params: { query: { part_id: [...partIds] } },
      });
      if (!data) throw new Error("Could not load the stock totals");
      return new Map(data.map((total: PartTotal) => [total.part_id, total.on_hand]));
    },
    enabled: partIds.length > 0,
  });
}

export function usePartTotals(partIds: readonly string[]) {
  return useQuery(partTotalsQuery(partIds));
}

/**
 * A stock change touches the inventory projection and the catalog numbers alike: the part
 * page reads its breakdown from inventory, but the parts list reads each part's total beside
 * catalog's own rows. Dropping both roots is what makes a received quantity show in place,
 * on the part page and the list, without a full reload (requirement 9.4).
 */
function useStockInvalidation() {
  const queryClient = useQueryClient();
  return () => refreshAfterWrite(queryClient, inventoryKeys.all, catalogKeys.all);
}

export function useReceiveStock() {
  const invalidate = useStockInvalidation();
  return useMutation({
    mutationFn: async (body: ReceiveRequest): Promise<BalanceResponse> => {
      const { data, error, response } = await api.POST("/api/inventory/receive", { body });
      if (data) return data;
      throw new InventoryRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export function useAdjustStock() {
  const invalidate = useStockInvalidation();
  return useMutation({
    mutationFn: async (body: AdjustRequest): Promise<BalanceResponse> => {
      const { data, error, response } = await api.POST("/api/inventory/adjust", { body });
      if (data) return data;
      throw new InventoryRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export function useMoveStock() {
  const invalidate = useStockInvalidation();
  return useMutation({
    mutationFn: async (body: MoveRequest): Promise<MoveResponse> => {
      const { data, error, response } = await api.POST("/api/inventory/move", { body });
      if (data) return data;
      throw new InventoryRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}
