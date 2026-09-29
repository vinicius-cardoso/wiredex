import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  Lifecycle,
  PartHolding,
  RefusalCode,
  RevisionDetails,
  RevisionRef,
  ShortageReport,
  Transition,
} from "@wiredex/api-client";
import { api } from "../../../shared/api/client";
import { refreshAfterWrite } from "../../../shared/api/refresh";
import { catalogKeys } from "../../catalog/catalog";
import { inventoryKeys } from "../../inventory/inventory";
import { bomKeys } from "../bom/bom";
import { projectKeys } from "../projects";

/**
 * The lifecycle caches: a revision's build (`revision`), a revision found by its id alone
 * (`ref`), and a part's holdings (`partHoldings`). They hang off their own root, apart from
 * the projects and BOM roots, so a transition can drop each of them together (requirement
 * 13.7).
 */
export const lifecycleKeys = {
  all: ["lifecycle"] as const,
  revision: (revisionId: string) => ["lifecycle", "revision", revisionId] as const,
  ref: (revisionId: string) => ["lifecycle", "ref", revisionId] as const,
  partHoldings: (partId: string) => ["lifecycle", "part-holdings", partId] as const,
};

export function lifecycleQuery(revisionId: string) {
  return queryOptions({
    queryKey: lifecycleKeys.revision(revisionId),
    queryFn: async (): Promise<Lifecycle> => {
      const { data } = await api.GET("/api/projects/revisions/{revision_id}/lifecycle", {
        params: { path: { revision_id: revisionId } },
      });
      if (!data) throw new Error("Could not load the revision's build");
      return data;
    },
  });
}

/** A revision's status, the transitions it allows, whether it can be deleted, and what it holds. */
export function useLifecycle(revisionId: string) {
  return useQuery(lifecycleQuery(revisionId));
}

export function revisionRefQuery(revisionId: string) {
  return queryOptions({
    queryKey: lifecycleKeys.ref(revisionId),
    queryFn: async (): Promise<RevisionRef> => {
      const { data } = await api.GET("/api/projects/revisions/{revision_id}", {
        params: { path: { revision_id: revisionId } },
      });
      if (!data) throw new Error("Could not load the revision");
      return data;
    },
  });
}

/** One revision named by its id alone, for a link from a unit or a part's holdings (10.2). */
export function useRevisionRef(revisionId: string) {
  return useQuery(revisionRefQuery(revisionId));
}

export function partHoldingsQuery(partId: string) {
  return queryOptions({
    queryKey: lifecycleKeys.partHoldings(partId),
    queryFn: async (): Promise<PartHolding[]> => {
      const { data } = await api.GET("/api/projects/parts/{part_id}/holdings", {
        params: { path: { part_id: partId } },
      });
      if (!data) throw new Error("Could not load the part's holdings");
      return data;
    },
  });
}

/** Each revision holding a part, with how many it reserves and how many its build consumed. */
export function usePartHoldings(partId: string) {
  return useQuery(partHoldingsQuery(partId));
}

/**
 * A refused transition, with the fields the API gave it (design's decision 14). `code` is what
 * the web translates; `report` is 09's shortage report for a `short`, and `unitCode` the code
 * of the unit a unit refusal names, when the workspace holds it.
 */
export class LifecycleRefusal extends Error {
  constructor(
    readonly status: number,
    readonly code: RefusalCode | null,
    readonly transition: Transition | null = null,
    readonly revisionStatus: RevisionDetails["status"] | null = null,
    readonly unitId: string | null = null,
    readonly unitCode: string | null = null,
    readonly report: ShortageReport | null = null,
    readonly detail = "",
  ) {
    super(detail || `the lifecycle API refused this with ${status}`);
  }

  static from(status: number, error: unknown): LifecycleRefusal {
    const detail = (error as { detail?: unknown } | null | undefined)?.detail;
    if (isRecord(detail) && typeof detail.code === "string") {
      return new LifecycleRefusal(
        status,
        detail.code as RefusalCode,
        (detail.transition as Transition | undefined) ?? null,
        (detail.status as RevisionDetails["status"] | undefined) ?? null,
        typeof detail.unit_id === "string" ? detail.unit_id : null,
        typeof detail.unit_code === "string" ? detail.unit_code : null,
        isRecord(detail.report) ? (detail.report as unknown as ShortageReport) : null,
        typeof detail.message === "string" ? detail.message : "",
      );
    }
    // A 404, or FastAPI's own 422 with no code: no code to translate, so the generic error.
    return new LifecycleRefusal(status, null);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * A transition moves the revision's status, its stock effect and its last change together, so
 * the new status shows in the revision panel, the project page's revisions and the project
 * list, and the BOM and every stock view on screen refresh in place (requirement 13.7). Each
 * mutation drops the lifecycle, projects, BOM, inventory and catalog roots.
 */
function useTransitionInvalidation() {
  const queryClient = useQueryClient();
  return () =>
    refreshAfterWrite(
      queryClient,
      lifecycleKeys.all,
      projectKeys.all,
      bomKeys.all,
      inventoryKeys.all,
      catalogKeys.all,
    );
}

export type Reserve = { revisionId: string; units: string[] };

export function useReserveRevision() {
  const invalidate = useTransitionInvalidation();
  return useMutation({
    mutationFn: async ({ revisionId, units }: Reserve): Promise<RevisionDetails> => {
      const { data, error, response } = await api.POST(
        "/api/projects/revisions/{revision_id}/reserve",
        { params: { path: { revision_id: revisionId } }, body: { units } },
      );
      if (data) return data;
      throw LifecycleRefusal.from(response.status, error);
    },
    onSuccess: invalidate,
  });
}

export function useCancelReservation() {
  const invalidate = useTransitionInvalidation();
  return useMutation({
    mutationFn: async (revisionId: string): Promise<RevisionDetails> => {
      const { data, error, response } = await api.POST(
        "/api/projects/revisions/{revision_id}/cancel",
        { params: { path: { revision_id: revisionId } } },
      );
      if (data) return data;
      throw LifecycleRefusal.from(response.status, error);
    },
    onSuccess: invalidate,
  });
}

export function useBuildRevision() {
  const invalidate = useTransitionInvalidation();
  return useMutation({
    mutationFn: async (revisionId: string): Promise<RevisionDetails> => {
      const { data, error, response } = await api.POST(
        "/api/projects/revisions/{revision_id}/build",
        { params: { path: { revision_id: revisionId } } },
      );
      if (data) return data;
      throw LifecycleRefusal.from(response.status, error);
    },
    onSuccess: invalidate,
  });
}

export type Dismantle = { revisionId: string; locationId: string };

export function useDismantleRevision() {
  const invalidate = useTransitionInvalidation();
  return useMutation({
    mutationFn: async ({ revisionId, locationId }: Dismantle): Promise<RevisionDetails> => {
      const { data, error, response } = await api.POST(
        "/api/projects/revisions/{revision_id}/dismantle",
        {
          params: { path: { revision_id: revisionId } },
          body: { location_id: locationId },
        },
      );
      if (data) return data;
      throw LifecycleRefusal.from(response.status, error);
    },
    onSuccess: invalidate,
  });
}
