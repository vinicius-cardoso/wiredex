import type {
  HistoryAction,
  HistoryOperation,
  HistoryRecordKind,
  HistoryRowKind,
} from "@wiredex/api-client";

/** What happened to a change's record, as a short phrase (decision 6). */
export function actionKey(action: HistoryAction) {
  return `history.action.${action}` as const;
}

/** A record's kind, as the feed names it beside the record. */
export function recordKindKey(kind: HistoryRecordKind) {
  return `history.record.${kind}` as const;
}

/** A row's kind: a part, a pin, a BOM line, a net... */
export function rowKindKey(kind: HistoryRowKind) {
  return `history.row.${kind}` as const;
}

/** What a change did to one row: added, changed or removed. */
export function operationKey(operation: HistoryOperation) {
  return `history.operation.${operation}` as const;
}

/**
 * The fields the tracked tables show, each with a word in both languages. A field outside the
 * list, from a table tracked later, is shown by its own name rather than not at all.
 */
const FIELDS = [
  "attributes",
  "based_on",
  "category_id",
  "changelog",
  "code",
  "color",
  "content",
  "description",
  "designator",
  "flashed_at",
  "forked_from",
  "framework",
  "functions",
  "key",
  "kind",
  "label",
  "line_id",
  "lot_id",
  "mac",
  "manufacturer",
  "mpn",
  "name",
  "net_id",
  "not_stocked",
  "notes",
  "number",
  "options",
  "package",
  "parent_id",
  "part_id",
  "path",
  "pin",
  "position",
  "quantity",
  "released_at",
  "required",
  "revision_id",
  "serial",
  "sha256",
  "size",
  "status",
  "summary",
  "tags",
  "target",
  "title",
  "tracked_individually",
  "trashed_at",
  "type",
  "unit",
  "unit_code",
  "version",
  "version_id",
  "voltage",
] as const;

type Field = (typeof FIELDS)[number];

function isKnown(name: string): name is Field {
  return (FIELDS as readonly string[]).includes(name);
}

/** A field's i18n key, or null for a field outside the list, shown by its name. */
export function fieldKey(name: string) {
  return isKnown(name) ? (`history.field.${name}` as const) : null;
}
