import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  MoveUnitRequest,
  ReceiveUnitsRequest,
  ReceiveUnitsResponse,
  RelabelUnitRequest,
  RetireReason,
  UnitResponse,
} from "@wiredex/api-client";
import { api } from "../../shared/api/client";
import { catalogKeys } from "../catalog/catalog";
import { detailOf, InventoryRefusal, inventoryKeys } from "./inventory";

/**
 * The unit caches hang under the same inventory root as the lots and balances, so one
 * invalidation of `inventory.all` refreshes a part's units, a location's units and the
 * per-location breakdown together. A search caches under its term.
 */
export const unitKeys = {
  ofPart: (partId: string) => ["inventory", "units", "of-part", partId] as const,
  ofLocation: (locationId: string) => ["inventory", "units", "of-location", locationId] as const,
  one: (unitId: string) => ["inventory", "units", "one", unitId] as const,
  search: (term: string) => ["inventory", "units", "search", term] as const,
};

/** A part's units, for the list under the stock breakdown (requirement 6.1, 8.1). */
export function unitsOfPartQuery(partId: string) {
  return queryOptions({
    queryKey: unitKeys.ofPart(partId),
    queryFn: async (): Promise<UnitResponse[]> => {
      const { data } = await api.GET("/api/inventory/parts/{part_id}/units", {
        params: { path: { part_id: partId } },
      });
      if (!data) throw new Error("Could not load the units");
      return data;
    },
  });
}

export function useUnitsOfPart(partId: string) {
  return useQuery(unitsOfPartQuery(partId));
}

/** One unit, for its page (requirement 8.3). */
export function unitQuery(unitId: string) {
  return queryOptions({
    queryKey: unitKeys.one(unitId),
    queryFn: async (): Promise<UnitResponse> => {
      const { data } = await api.GET("/api/inventory/units/{unit_id}", {
        params: { path: { unit_id: unitId } },
      });
      if (!data) throw new Error("Could not load the unit");
      return data;
    },
  });
}

export function useUnit(unitId: string) {
  return useQuery(unitQuery(unitId));
}

/**
 * A workspace search over code, serial and MAC (requirement 8.4). Skipped until the term is
 * non-empty: an empty search is nothing to ask about, and the box starts blank.
 */
export function unitSearchQuery(term: string) {
  return queryOptions({
    queryKey: unitKeys.search(term),
    queryFn: async (): Promise<UnitResponse[]> => {
      const { data } = await api.GET("/api/inventory/units", {
        params: { query: { search: term } },
      });
      if (!data) throw new Error("Could not search the units");
      return data;
    },
    enabled: term.trim() !== "",
  });
}

export function useUnitSearch(term: string) {
  return useQuery(unitSearchQuery(term));
}

/**
 * A unit change touches the inventory projection and the catalog numbers alike: a receipt,
 * retire or move shifts a lot's `on_hand`, which the part page reads from inventory and the
 * parts list reads beside catalog's rows. Dropping both roots is what makes the change show
 * in place without a full reload (requirement 8.1).
 */
function useUnitInvalidation() {
  const queryClient = useQueryClient();
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: inventoryKeys.all }),
      queryClient.invalidateQueries({ queryKey: catalogKeys.all }),
    ]);
  };
}

export function useReceiveUnits() {
  const invalidate = useUnitInvalidation();
  return useMutation({
    mutationFn: async (body: ReceiveUnitsRequest): Promise<ReceiveUnitsResponse> => {
      const { data, error, response } = await api.POST("/api/inventory/units", { body });
      if (data) return data;
      throw new InventoryRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export type UnitRelabel = { unitId: string; body: RelabelUnitRequest };

export function useRelabelUnit() {
  const invalidate = useUnitInvalidation();
  return useMutation({
    mutationFn: async ({ unitId, body }: UnitRelabel): Promise<UnitResponse> => {
      const { data, error, response } = await api.PATCH("/api/inventory/units/{unit_id}", {
        params: { path: { unit_id: unitId } },
        body,
      });
      if (data) return data;
      throw new InventoryRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export type UnitMove = { unitId: string; body: MoveUnitRequest };

export function useMoveUnit() {
  const invalidate = useUnitInvalidation();
  return useMutation({
    mutationFn: async ({ unitId, body }: UnitMove): Promise<UnitResponse> => {
      const { data, error, response } = await api.POST("/api/inventory/units/{unit_id}/move", {
        params: { path: { unit_id: unitId } },
        body,
      });
      if (data) return data;
      throw new InventoryRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export type UnitRetire = { unitId: string; reason: RetireReason };

export function useRetireUnit() {
  const invalidate = useUnitInvalidation();
  return useMutation({
    mutationFn: async ({ unitId, reason }: UnitRetire): Promise<UnitResponse> => {
      const { data, error, response } = await api.POST("/api/inventory/units/{unit_id}/retire", {
        params: { path: { unit_id: unitId } },
        body: { reason },
      });
      if (data) return data;
      throw new InventoryRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

export function useUnretireUnit() {
  const invalidate = useUnitInvalidation();
  return useMutation({
    mutationFn: async (unitId: string): Promise<UnitResponse> => {
      const { data, error, response } = await api.POST("/api/inventory/units/{unit_id}/unretire", {
        params: { path: { unit_id: unitId } },
      });
      if (data) return data;
      throw new InventoryRefusal(response.status, detailOf(error));
    },
    onSuccess: invalidate,
  });
}

/**
 * The canonical `aa:bb:cc:dd:ee:ff` for an accepted MAC spelling, or null when it isn't six
 * hex octets. It mirrors the server's `Mac` value object so the dialog can show the form the
 * unit will hold — but only once the input validates, never rewriting what was typed before
 * then (requirement 8.5). Accepts the colon, hyphen, Cisco dot and bare spellings.
 */
export function canonicalMac(input: string): string | null {
  const hex = input.trim().replace(/[.:-]/g, "").toLowerCase();
  if (!/^[0-9a-f]{12}$/.test(hex)) return null;
  return (hex.match(/.{2}/g) ?? []).join(":");
}

export function useDeleteUnit() {
  const invalidate = useUnitInvalidation();
  return useMutation({
    mutationFn: async (unitId: string): Promise<void> => {
      const { error, response } = await api.DELETE("/api/inventory/units/{unit_id}", {
        params: { path: { unit_id: unitId } },
      });
      // 404 is what was asked for: the unit is gone either way. A 409 (an in-stock unit)
      // lands here with the message that says it has to be retired first (requirement 8.3).
      if (!response.ok && response.status !== 404) {
        throw new InventoryRefusal(response.status, detailOf(error));
      }
    },
    onSuccess: invalidate,
  });
}
