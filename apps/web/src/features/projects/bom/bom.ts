import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Bom, BomField, BomLine, BomLineChange, BomRefusalCode } from "@wiredex/api-client";
import { api } from "../../../shared/api/client";
import { refreshAfterWrite } from "../../../shared/api/refresh";
import { netlistKeys } from "../netlist/netlist";
import { detailOf, projectKeys } from "../projects";

/**
 * Every BOM hangs off one root, apart from the projects root: a line write drops its own
 * revision's BOM, and a quick-add or an import drops them all, since a new part or new stock
 * can change any report (requirement 11.14).
 */
export const bomKeys = {
  all: ["bom"] as const,
  revision: (revisionId: string) => ["bom", "revision", revisionId] as const,
};

export function bomQuery(revisionId: string) {
  return queryOptions({
    queryKey: bomKeys.revision(revisionId),
    queryFn: async (): Promise<Bom> => {
      const { data, error, response } = await api.GET("/api/projects/revisions/{revision_id}/bom", {
        params: { path: { revision_id: revisionId } },
      });
      if (data) return data;
      throw BomRefusal.from(response.status, error);
    },
  });
}

/**
 * A revision's lines, its shortage report and whether it can change. The report is computed
 * by the API at every read (requirement 6.7), so the query is simply fetched again whenever
 * something it depends on may have moved.
 */
export function useBom(revisionId: string) {
  return useQuery(bomQuery(revisionId));
}

/** FastAPI names a refused body field by its wire name; the editor knows its fields by theirs. */
const WIRE_FIELDS: Record<string, BomField> = {
  part_id: "part",
  designators: "designators",
  quantity: "quantity",
  notes: "notes",
};

/**
 * A refused line write, with the structure the API gave it (design's Error Handling).
 *
 * A refused value answers a `BomRefusalResponse`: the code the editor translates, the field it
 * shows it on, the designator or item it names and, for a designator another line holds, that
 * line. A body the request schema refuses answers FastAPI's own list instead, whose first entry
 * still names its field. Anything else (a 404) keeps only its sentence.
 */
export class BomRefusal extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly code: BomRefusalCode | null = null,
    readonly field: BomField | null = null,
    readonly item: string | null = null,
    readonly line: string | null = null,
  ) {
    super(detail || `the BOM API refused this with ${status}`);
  }

  static from(status: number, error: unknown): BomRefusal {
    const detail = (error as { detail?: unknown } | null | undefined)?.detail;
    if (isRecord(detail) && typeof detail.code === "string") {
      return new BomRefusal(
        status,
        typeof detail.message === "string" ? detail.message : "",
        detail.code as BomRefusalCode,
        typeof detail.field === "string" ? (detail.field as BomField) : null,
        typeof detail.item === "string" ? detail.item : null,
        typeof detail.line === "string" ? detail.line : null,
      );
    }
    if (Array.isArray(detail) && isRecord(detail[0]) && Array.isArray(detail[0].loc)) {
      const wire = detail[0].loc.at(-1);
      const field = typeof wire === "string" ? (WIRE_FIELDS[wire] ?? null) : null;
      return new BomRefusal(status, detailOf(error), null, field);
    }
    return new BomRefusal(status, detailOf(error));
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export type BomLineAddition = { revisionId: string; body: BomLineChange };

export function useAddBomLine() {
  const invalidate = useBomInvalidation();
  return useMutation({
    mutationFn: async ({ revisionId, body }: BomLineAddition): Promise<BomLine> => {
      const { data, error, response } = await api.POST(
        "/api/projects/revisions/{revision_id}/bom/lines",
        { params: { path: { revision_id: revisionId } }, body },
      );
      if (data) return data;
      throw BomRefusal.from(response.status, error);
    },
    // Awaited, so the new line is in the table by the time the row clears for the next one.
    onSuccess: (_line, { revisionId }) => invalidate(revisionId),
  });
}

export type BomLineEdit = { revisionId: string; lineId: string; body: BomLineChange };

export function useUpdateBomLine() {
  const invalidate = useBomInvalidation();
  return useMutation({
    mutationFn: async ({ revisionId, lineId, body }: BomLineEdit): Promise<BomLine> => {
      const { data, error, response } = await api.PATCH(
        "/api/projects/revisions/{revision_id}/bom/lines/{line_id}",
        { params: { path: { revision_id: revisionId, line_id: lineId } }, body },
      );
      if (data) return data;
      throw BomRefusal.from(response.status, error);
    },
    onSuccess: (_line, { revisionId }) => invalidate(revisionId),
  });
}

export type BomLineRemoval = { revisionId: string; lineId: string };

export function useRemoveBomLine() {
  const invalidate = useBomInvalidation();
  return useMutation({
    mutationFn: async ({ revisionId, lineId }: BomLineRemoval): Promise<void> => {
      const { error, response } = await api.DELETE(
        "/api/projects/revisions/{revision_id}/bom/lines/{line_id}",
        { params: { path: { revision_id: revisionId, line_id: lineId } } },
      );
      // A 409 for a revision that stopped being a draft; a 404 is already gone.
      if (!response.ok && response.status !== 404) throw BomRefusal.from(response.status, error);
    },
    onSuccess: (_nothing, { revisionId }) => invalidate(revisionId),
  });
}

/**
 * A line write changes its revision's BOM and report, and moves the revision's last change,
 * which the project list orders by (requirement 5.3), so the projects root goes too. It also
 * changes what the revision's pin references resolve to (spec 11, requirement 10.10).
 */
function useBomInvalidation() {
  const queryClient = useQueryClient();
  return (revisionId: string) =>
    refreshAfterWrite(
      queryClient,
      bomKeys.revision(revisionId),
      netlistKeys.revision(revisionId),
      projectKeys.all,
    );
}
