import { useMutation, useQueryClient } from "@tanstack/react-query";
import type {
  CellProblem,
  ImportPreview,
  ImportRequest,
  ImportResult,
  QuickAddRequest,
  QuickAddResponse,
} from "@wiredex/api-client";
import { api } from "../../../shared/api/client";
import { refreshAfterWrite } from "../../../shared/api/refresh";
import { catalogKeys } from "../../catalog/catalog";
import { detailOf, inventoryKeys } from "../inventory";

/** The part that already holds a quick-add's manufacturer and part number (requirement 1.6). */
export type TakenPart = { partId: string; name: string };

/**
 * Why a sheet can't be read at all (requirement 4.6), as the API's `SheetRefusalName` spells
 * it. That body rides an HTTPException's `detail`, so the generated client doesn't carry the
 * type; the list is kept here, and a code outside it keeps only the server's sentence.
 */
export const SHEET_REFUSALS = [
  "not_utf8",
  "empty",
  "unknown_column",
  "duplicate_column",
  "too_many_columns",
  "too_many_rows",
] as const;

export type SheetRefusalCode = (typeof SHEET_REFUSALS)[number];

/** An unreadable sheet's code, and the column it is about when it is about one. */
export type SheetRefusal = { code: SheetRefusalCode; column: string | null };

/**
 * An intake refusal, with the structure the API gave it (design's Error Handling).
 *
 * These bodies ride an HTTPException's `detail` rather than a route's response model, so they
 * aren't in the generated schema and are read here from the error body: a 422 lists every
 * problem with its column and code, or names why a sheet can't be read; a 409 names the part
 * holding the number. Anything else (a 404 for a duplicate's missing source, an import whose
 * outcome changed, FastAPI's own list for a body the schema refuses) keeps only its sentence.
 */
export class IntakeRefusal extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly problems: readonly CellProblem[] = [],
    readonly taken: TakenPart | null = null,
    readonly sheet: SheetRefusal | null = null,
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
    const sheet = isSheetRefusal(detail.code)
      ? { code: detail.code, column: typeof detail.column === "string" ? detail.column : null }
      : null;
    return new IntakeRefusal(status, message, problems, taken, sheet);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isProblem(value: unknown): value is CellProblem {
  return isRecord(value) && typeof value.code === "string" && typeof value.message === "string";
}

function isSheetRefusal(value: unknown): value is SheetRefusalCode {
  return typeof value === "string" && (SHEET_REFUSALS as readonly string[]).includes(value);
}

/**
 * A quick-add or an import writes into the catalog (the parts) and the inventory (lots,
 * balances and units) at once, so both roots are dropped: the parts list, a part's stock and
 * its units all show the addition in place, without a reload (requirement 11.7).
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

/**
 * What every row of a sheet would do (requirement 7). A plan with problems is still an answer,
 * not an error (7.5); only a sheet that can't be read is refused. A preview writes nothing, so
 * nothing is invalidated. It is a mutation because the owner asks for it with a button, and
 * each ask is for the text as it stands then.
 */
export function usePreviewImport() {
  return useMutation({
    mutationFn: async (csv: string): Promise<ImportPreview> => {
      const { data, error, response } = await api.POST("/api/inventory/imports/preview", {
        body: { csv },
      });
      if (data) return data;
      throw IntakeRefusal.from(response.status, error);
    },
  });
}

/**
 * Imports the sheet a clean preview showed, sending that preview's digest back (requirement
 * 8). A 422 carries the problems the plan has now, and a 409 says its outcome changed since the
 * preview; either way nothing was written.
 */
export function useImportSheet() {
  const invalidate = useIntakeInvalidation();
  return useMutation({
    mutationFn: async (body: ImportRequest): Promise<ImportResult> => {
      const { data, error, response } = await api.POST("/api/inventory/imports", { body });
      if (data) return data;
      throw IntakeRefusal.from(response.status, error);
    },
    onSuccess: invalidate,
  });
}

/** The template's address: a plain download, which the session cookie goes along with. */
export const IMPORT_TEMPLATE_URL = "/api/inventory/imports/template";
