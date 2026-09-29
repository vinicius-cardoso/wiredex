import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Net, NetChange, NetField, Netlist, NetRefusalCode } from "@wiredex/api-client";
import { api } from "../../../shared/api/client";
import { refreshAfterWrite } from "../../../shared/api/refresh";
import { detailOf, projectKeys } from "../projects";
import { pinUsageKeys } from "./pinUsage";

/**
 * Every netlist hangs off one root, apart from the projects root: a net write drops its own
 * revision's netlist, and a BOM write or a transition drops it too, since both change what a
 * reference resolves to or whether the netlist can change (spec 11, requirement 10.10).
 */
export const netlistKeys = {
  all: ["netlist"] as const,
  revision: (revisionId: string) => ["netlist", "revision", revisionId] as const,
};

export function netlistQuery(revisionId: string) {
  return queryOptions({
    queryKey: netlistKeys.revision(revisionId),
    queryFn: async (): Promise<Netlist> => {
      const { data, error, response } = await api.GET(
        "/api/projects/revisions/{revision_id}/netlist",
        { params: { path: { revision_id: revisionId } } },
      );
      if (data) return data;
      throw NetRefusal.from(response.status, error);
    },
  });
}

/**
 * A revision's nets, what each reference resolves to and what the editor picks from. The
 * resolutions are computed by the API at every read (requirement 4.3), so the query is simply
 * fetched again whenever something they depend on may have moved.
 */
export function useNetlist(revisionId: string) {
  return useQuery(netlistQuery(revisionId));
}

/**
 * A refused net write, with the structure the API gave it (spec 11, Error Handling): the code
 * the editor translates, the field it shows it on, the reference as typed, an ambiguous pin's
 * candidates and a taken name's net. A body the request schema refuses answers FastAPI's own
 * list instead, whose first entry still names its field. Anything else keeps its sentence.
 */
export class NetRefusal extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly code: NetRefusalCode | null = null,
    readonly field: NetField | null = null,
    readonly item: string | null = null,
    readonly candidates: string[] = [],
    readonly net: string | null = null,
  ) {
    super(detail || `the netlist API refused this with ${status}`);
  }

  static from(status: number, error: unknown): NetRefusal {
    const detail = (error as { detail?: unknown } | null | undefined)?.detail;
    if (isRecord(detail) && typeof detail.code === "string") {
      return new NetRefusal(
        status,
        typeof detail.message === "string" ? detail.message : "",
        detail.code as NetRefusalCode,
        typeof detail.field === "string" ? (detail.field as NetField) : null,
        typeof detail.item === "string" ? detail.item : null,
        Array.isArray(detail.candidates) ? detail.candidates.map(String) : [],
        typeof detail.net === "string" ? detail.net : null,
      );
    }
    if (Array.isArray(detail) && isRecord(detail[0]) && Array.isArray(detail[0].loc)) {
      const wire = detail[0].loc.at(-1);
      const field = wire === "name" || wire === "color" || wire === "notes" || wire === "pins";
      return new NetRefusal(status, detailOf(error), null, field ? (wire as NetField) : null);
    }
    return new NetRefusal(status, detailOf(error));
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export type NetAddition = { revisionId: string; body: NetChange };

export function useAddNet() {
  const invalidate = useNetlistInvalidation();
  return useMutation({
    mutationFn: async ({ revisionId, body }: NetAddition): Promise<Net> => {
      const { data, error, response } = await api.POST(
        "/api/projects/revisions/{revision_id}/netlist/nets",
        { params: { path: { revision_id: revisionId } }, body },
      );
      if (data) return data;
      throw NetRefusal.from(response.status, error);
    },
    // Awaited, so the new net is in the table by the time the row clears for the next one.
    onSuccess: (_net, { revisionId }) => invalidate(revisionId),
  });
}

export type NetEdit = { revisionId: string; netId: string; body: NetChange };

export function useUpdateNet() {
  const invalidate = useNetlistInvalidation();
  return useMutation({
    mutationFn: async ({ revisionId, netId, body }: NetEdit): Promise<Net> => {
      const { data, error, response } = await api.PATCH(
        "/api/projects/revisions/{revision_id}/netlist/nets/{net_id}",
        { params: { path: { revision_id: revisionId, net_id: netId } }, body },
      );
      if (data) return data;
      throw NetRefusal.from(response.status, error);
    },
    onSuccess: (_net, { revisionId }) => invalidate(revisionId),
  });
}

export type NetRemoval = { revisionId: string; netId: string };

export function useRemoveNet() {
  const invalidate = useNetlistInvalidation();
  return useMutation({
    mutationFn: async ({ revisionId, netId }: NetRemoval): Promise<void> => {
      const { error, response } = await api.DELETE(
        "/api/projects/revisions/{revision_id}/netlist/nets/{net_id}",
        { params: { path: { revision_id: revisionId, net_id: netId } } },
      );
      // A 409 for a revision that stopped being a draft; a 404 is already gone.
      if (!response.ok && response.status !== 404) throw NetRefusal.from(response.status, error);
    },
    onSuccess: (_nothing, { revisionId }) => invalidate(revisionId),
  });
}

/**
 * A net write changes its revision's netlist and moves the revision's last change, which the
 * project list orders by (requirement 5.3), so the projects root goes too, and every part's
 * pin usage, which names the net (spec 12, requirement 10.7).
 */
function useNetlistInvalidation() {
  const queryClient = useQueryClient();
  return (revisionId: string) =>
    refreshAfterWrite(
      queryClient,
      netlistKeys.revision(revisionId),
      projectKeys.all,
      pinUsageKeys.all,
    );
}
