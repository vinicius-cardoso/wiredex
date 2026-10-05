import {
  keepPreviousData,
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type {
  MoveUnitRequest,
  ReceiveUnitsRequest,
  ReceiveUnitsResponse,
  RelabelUnitRequest,
  RetireReason,
  UnitPart,
  UnitResponse,
  UnitStatus,
} from "@wiredex/api-client";
import { api } from "../../shared/api/client";
import { refreshAfterWrite } from "../../shared/api/refresh";
import { catalogKeys } from "../catalog/catalog";
import { trashKeys } from "../trash/keys";
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
  boards: (filters: BoardFilters) => ["inventory", "units", "boards", filters] as const,
  parts: ["inventory", "units", "parts"] as const,
};

/** The four statuses, in the order a board moves through them, for the list's filter. */
export const UNIT_STATUSES = [
  "in_stock",
  "reserved",
  "in_use",
  "retired",
] as const satisfies readonly UnitStatus[];

/** How many boards one read of the list answers, as the API caps it. */
export const BOARDS_LIMIT = 200;

/** What the boards list is narrowed by: a code, serial or MAC fragment, a status, a part. */
export type BoardFilters = { q: string; status: UnitStatus | null; partId: string | null };

/** The boards list's filters as the address holds them, every default left out. */
export type BoardSearch = { q?: string; status?: UnitStatus; part?: string };

/**
 * The address, parsed. Anything that doesn't fit is dropped rather than thrown, so a
 * hand-edited link still opens the list.
 */
export function validateBoardSearch(raw: Record<string, unknown>): BoardSearch {
  const search: BoardSearch = {};
  const q = typeof raw.q === "string" ? raw.q.trim() : "";
  if (q) search.q = q;
  const status = UNIT_STATUSES.find((known) => known === raw.status);
  if (status) search.status = status;
  const part = typeof raw.part === "string" ? raw.part.trim() : "";
  if (part) search.part = part;
  return search;
}

/**
 * The workspace's boards, newest first, at most 200, narrowed by the filters (the boards
 * list). Every row carries its part's name and its location, so the list needs no read per
 * row.
 */
export function boardsQuery(filters: BoardFilters) {
  return queryOptions({
    queryKey: unitKeys.boards(filters),
    queryFn: async (): Promise<UnitResponse[]> => {
      // null for what isn't set: the client drops it from the query string.
      const search = filters.q.trim();
      const query = {
        ...(search ? { search } : {}),
        status: filters.status,
        part_id: filters.partId,
      };
      const { data } = await api.GET("/api/inventory/units", { params: { query } });
      if (!data) throw new Error("Could not load the boards");
      return data;
    },
    // A new filter keeps the last rows on screen until its own land, so the table doesn't
    // blink empty while typing.
    placeholderData: keepPreviousData,
  });
}

export function useBoards(filters: BoardFilters) {
  return useQuery(boardsQuery(filters));
}

/**
 * The parts the bench's boards are of, each with how many, by name, the ones the catalog no
 * longer names last: the boards list's part filter, whatever page of boards is showing. Under
 * the inventory root, so a unit write refreshes it with the list.
 */
export function boardPartsQuery() {
  return queryOptions({
    queryKey: unitKeys.parts,
    queryFn: async (): Promise<UnitPart[]> => {
      const { data } = await api.GET("/api/inventory/units/parts");
      if (!data) throw new Error("Could not load the boards' parts");
      return data;
    },
  });
}

export function useBoardParts() {
  return useQuery(boardPartsQuery());
}

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

/** The boards sitting in a location, for its panel (requirement 6.2): never one in use. */
export function unitsOfLocationQuery(locationId: string) {
  return queryOptions({
    queryKey: unitKeys.ofLocation(locationId),
    queryFn: async (): Promise<UnitResponse[]> => {
      const { data } = await api.GET("/api/inventory/locations/{location_id}/units", {
        params: { path: { location_id: locationId } },
      });
      if (!data) throw new Error("Could not load the location's units");
      return data;
    },
  });
}

export function useUnitsOfLocation(locationId: string) {
  return useQuery(unitsOfLocationQuery(locationId));
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
  return () => refreshAfterWrite(queryClient, inventoryKeys.all, catalogKeys.all);
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

/** Moves a retired unit to the trash (16-soft-delete-and-trash, 1.1), which lists it next. */
export function useDeleteUnit() {
  const queryClient = useQueryClient();
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
    // Not awaited, as projects' and firmware's deletes aren't: the page leaves for the list at
    // once, rather than waiting on a refetch of the unit it just moved, whose 404 is retried.
    onSuccess: () =>
      void refreshAfterWrite(queryClient, inventoryKeys.all, catalogKeys.all, trashKeys.all),
  });
}
