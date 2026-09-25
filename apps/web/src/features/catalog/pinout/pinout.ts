import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Pinout, PinoutReplacement } from "@wiredex/api-client";
import { api } from "../../../shared/api/client";
import { catalogKeys } from "../catalog";

/** The cell a refusal is about, spelled the way the API spells it (requirement 3.1). */
export type PinField = "number" | "label" | "type" | "functions" | "voltage";

const FIELDS: readonly PinField[] = ["number", "label", "type", "functions", "voltage"];

export function pinoutQuery(partId: string) {
  return queryOptions({
    queryKey: catalogKeys.pinout(partId),
    queryFn: async (): Promise<Pinout> => {
      const { data } = await api.GET("/api/catalog/parts/{part_id}/pinout", {
        params: { path: { part_id: partId } },
      });
      if (!data) throw new Error("Could not load the pinout");
      return data;
    },
  });
}

/**
 * A part's pins, in their saved order. `enabled` is how the part page skips the request for
 * a part whose `pin_count` is 0: the part itself already says there is nothing to read.
 */
export function usePinout(partId: string, { enabled = true } = {}) {
  return useQuery({ ...pinoutQuery(partId), enabled });
}

/**
 * A refused pin table, with the row and the cell the API named instead of a sentence to
 * read, so the editor can mark the input that has to change (requirements 3.1 to 3.3).
 * Both are null when the table was refused as a whole, as too many pins is.
 */
export class PinoutRefusal extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly row: number | null = null,
    readonly field: PinField | null = null,
  ) {
    super(message || `the pinout was refused with ${status}`);
  }
}

/** Replaces the part's whole pinout: the table is saved as a table, never pin by pin. */
export function useReplacePinout(partId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: PinoutReplacement): Promise<Pinout> => {
      const { data, error, response } = await api.PUT("/api/catalog/parts/{part_id}/pinout", {
        params: { path: { part_id: partId } },
        body,
      });
      if (data) return data;
      throw refusalOf(response.status, error);
    },
    // The part carries `pin_count` and its own `updated_at`, so saving pins makes both the
    // pinout and the part stale.
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: catalogKeys.pinout(partId) }),
        queryClient.invalidateQueries({ queryKey: catalogKeys.part(partId) }),
      ]);
    },
  });
}

/**
 * What the API refused, read from either shape it answers with: the structured detail a
 * refused table gets, or the plain message every other catalog refusal carries, a 404's
 * included.
 */
function refusalOf(status: number, error: unknown): PinoutRefusal {
  const detail = (error as { detail?: unknown } | null | undefined)?.detail;
  const refused = rowRefusal(detail);
  if (refused) return new PinoutRefusal(status, refused.message, refused.row, refused.field);
  return new PinoutRefusal(status, typeof detail === "string" ? detail : "");
}

type RowRefusal = { message: string; row: number | null; field: PinField | null };

/**
 * The `{message, row, field}` detail of a refused table, or null for anything else. An
 * unknown field name is dropped rather than trusted: the message still says what is wrong.
 */
function rowRefusal(detail: unknown): RowRefusal | null {
  if (typeof detail !== "object" || detail === null) return null;
  const { message, row, field } = detail as Record<string, unknown>;
  if (typeof message !== "string") return null;
  return {
    message,
    row: typeof row === "number" ? row : null,
    field: FIELDS.find((name) => name === field) ?? null,
  };
}
