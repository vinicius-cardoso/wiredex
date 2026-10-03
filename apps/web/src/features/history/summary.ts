import type {
  HistoryAction,
  HistoryChange,
  HistoryFieldChange,
  HistoryRowChange,
} from "@wiredex/api-client";

/**
 * What a folded change says on its second line, beyond what its action already says: the one
 * field it changed, before and after; how many fields, and which; the one row it added or
 * removed; or how many rows it wrote, the first of them named.
 */
export type ChangeSummary =
  | { type: "field"; row: HistoryRowChange; own: boolean; field: HistoryFieldChange }
  | { type: "fields"; row: HistoryRowChange; own: boolean; fields: HistoryFieldChange[] }
  | { type: "row"; row: HistoryRowChange }
  | { type: "rows"; count: number; rows: HistoryRowChange[] }
  | { type: "nothing" };

/** The actions a record's `trashed_at` field already says, so the field adds nothing. */
const TRASH_ACTIONS: ReadonlySet<HistoryAction> = new Set([
  "moved_to_trash",
  "restored_from_trash",
]);

/**
 * The line a change folds to. A change lists its record's own row first, when it wrote one, so
 * a row of the record's kind is the record itself, and anything else is what it holds: a pin of
 * a part, a source file of a firmware's version. Counting goes by every row the change wrote,
 * the ones past the first twenty included.
 */
export function summarize(change: HistoryChange): ChangeSummary {
  const total = change.rows.length + change.more_rows;
  const [row] = change.rows;
  if (total > 1 || row === undefined) {
    return total > 0 ? { type: "rows", count: total, rows: change.rows } : { type: "nothing" };
  }
  if (row.operation !== "update") return { type: "row", row };

  const fields = TRASH_ACTIONS.has(change.action)
    ? row.fields.filter((field) => field.name !== "trashed_at")
    : row.fields;
  const own = row.kind === change.record.kind;
  const [field] = fields;
  if (field === undefined) return { type: "nothing" };
  if (fields.length === 1) return { type: "field", row, own, field };
  return { type: "fields", row, own, fields };
}

/** Past this many characters, or with a line break, a value gets a box of its own to scroll in. */
export const LONG_VALUE = 120;

/** Whether a value is long enough to scroll inside its own box when a change is unfolded. */
export function isLongValue(text: string): boolean {
  return text.length > LONG_VALUE || text.includes("\n");
}
