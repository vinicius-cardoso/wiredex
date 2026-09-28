import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { CellProblem, QuickAddRequest, QuickAddResponse } from "@wiredex/api-client";
import { api } from "../../../shared/api/client";
import { refreshAfterWrite } from "../../../shared/api/refresh";
import { catalogKeys } from "../../catalog/catalog";
import { detailOf, inventoryKeys } from "../inventory";

/** The part that already holds a quick-add's manufacturer and part number (requirement 1.6). */
export type TakenPart = { partId: string; name: string };

/**
 * An intake refusal, with the structure the API gave it (design's Error Handling).
 *
 * These bodies ride an HTTPException's `detail` rather than a route's response model, so they
 * aren't in the generated schema and are read here from the error body: a 422 lists every
 * problem with its column and code, and a 409 names the part holding the number. Anything else
 * (a 404 for a duplicate's missing source, FastAPI's own list for a body the schema refuses)
 * keeps only its sentence.
 */
export class IntakeRefusal extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly problems: readonly CellProblem[] = [],
    readonly taken: TakenPart | null = null,
  ) {
    super(detail || `the inventory refused this with ${status}`);
  }

  static from(status: number, error: unknown): IntakeRefusal {
    const detail = (error as { detail?: unknown } | null | undefined)?.detail;
    if (!isRecord(detail)) return new IntakeRefusal(status, detailOf(error));
    const message = typeof detail.message === "string" ? detail.message : "";
    const problems = Array.isArray(detail.problems) ? detail.problems.filter(isProblem) : [];
    const taken =
      typeof detail.part_id === "string" && typeof detail.name === "string"
        ? { partId: detail.part_id, name: detail.name }
        : null;
    return new IntakeRefusal(status, message, problems, taken);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isProblem(value: unknown): value is CellProblem {
  return isRecord(value) && typeof value.code === "string" && typeof value.message === "string";
}

/**
 * A quick-add writes into the catalog (the part) and the inventory (its lot, balance and
 * units) at once, so both roots are dropped: the parts list, a part's stock and its units all
 * show the addition in place, without a reload (requirement 11.7).
 */
function useIntakeInvalidation() {
  const queryClient = useQueryClient();
  return () => refreshAfterWrite(queryClient, catalogKeys.all, inventoryKeys.all);
}

export function useQuickAddPart() {
  const invalidate = useIntakeInvalidation();
  return useMutation({
    mutationFn: async (body: QuickAddRequest): Promise<QuickAddResponse> => {
      const { data, error, response } = await api.POST("/api/inventory/quick-add", { body });
      if (data) return data;
      throw IntakeRefusal.from(response.status, error);
    },
    onSuccess: invalidate,
  });
}
