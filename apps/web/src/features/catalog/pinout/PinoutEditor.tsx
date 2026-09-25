import type { PartDetails, Pin, PinoutReplacement } from "@wiredex/api-client";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { type PasteMode, PastePanel } from "./PastePanel";
import type { ParsedRow } from "./paste";
import { type PinField, PinoutRefusal, usePinout, useReplacePinout } from "./pinout";
import { isPinType, PIN_TYPES } from "./pinTypes";

/** The five cells of a row, in the order the table shows them; `PinField` is what a refusal names. */
const COLUMNS = [
  "number",
  "label",
  "type",
  "functions",
  "voltage",
] as const satisfies readonly PinField[];

const control = "w-full rounded-md border border-border-strong bg-surface px-2 py-1 text-text";
const action = "rounded-md border border-border-strong px-2 py-1 text-sm hover:bg-surface-2";
const cell = "py-1 pr-2 align-top last:pr-0";

/**
 * One row being edited: text in every cell, and a key of its own. The key isn't the pin
 * number, because a row may be empty or repeat another while it is being typed, and React
 * still has to follow it through a move.
 */
type Row = { key: string } & Record<PinField, string>;

type PinoutEditorProps = { part: PartDetails; onClose: () => void };

/**
 * A part's pinout, as a table to type or paste into (requirement 6.1). The table is saved
 * whole: the API replaces the pinout with what is sent, so a pin is never half-saved.
 */
export function PinoutEditor({ part, onClose }: PinoutEditorProps) {
  const { t } = useTranslation();
  const headingId = useId();
  // A part with no pins asks for nothing, as the section doesn't either: there is an empty
  // table to start from and the part itself already said so.
  const pinout = usePinout(part.id, { enabled: part.pin_count > 0 });
  const loaded = !pinout.isLoading && !pinout.isError;

  return (
    <section aria-labelledby={headingId} className="grid gap-3">
      <h2 id={headingId} className="font-display text-xl font-semibold">
        {t("catalog.pinout.editor.title")}
      </h2>

      {pinout.isLoading && <p className="text-muted">{t("catalog.pinout.loading")}</p>}
      {pinout.isError && (
        <p role="alert" className="text-crit">
          {t("catalog.pinout.error")}
        </p>
      )}
      {loaded && <PinTable partId={part.id} pins={pinout.data?.pins ?? []} onClose={onClose} />}
    </section>
  );
}

type PinTableProps = { partId: string; pins: Pin[]; onClose: () => void };

/**
 * The rows themselves, seeded once from what is stored. Once from a good reason: a refetch
 * behind the editor, and a save the API refuses, must both leave what was typed alone
 * (requirement 6.9).
 */
function PinTable({ partId, pins, onClose }: PinTableProps) {
  const { t } = useTranslation();
  const save = useReplacePinout(partId);
  const [startingRows] = useState(() => pins.map(rowOfPin));
  const [rows, setRows] = useState(startingRows);
  const [pasting, setPasting] = useState(false);
  const [askingToDiscard, setAskingToDiscard] = useState(false);
  const keys = useRef(0);
  const messageId = useId();

  const refusal = save.error instanceof PinoutRefusal ? save.error : null;
  // The API's own words when it has any: a refused row says which row and what about it.
  const failure = save.isError ? (refusal?.message ?? t("catalog.pinout.editor.saveError")) : null;
  const unsaved = signature(rows) !== signature(startingRows);

  /** A key nothing else holds, for a row that has no stored pin behind it yet. */
  function nextKey(): string {
    keys.current += 1;
    return `new-${keys.current}`;
  }

  function edit(index: number, column: PinField, value: string) {
    setRows((current) =>
      current.map((row, at) => {
        if (at !== index) return row;
        const edited = { ...row };
        edited[column] = value;
        return edited;
      }),
    );
  }

  function addRow() {
    const row = emptyRow(nextKey());
    setRows((current) => [...current, row]);
  }

  function applyPaste(parsed: ParsedRow[], mode: PasteMode) {
    const batch = nextKey();
    const pasted = parsed.map((row, at) => rowOfParsed(row, `${batch}-${at}`));
    // Either the table the paste describes, or the rows it adds to the end of this one
    // (requirement 6.8). Neither saves anything: the table is still a table.
    setRows((current) => (mode === "replace" ? pasted : [...current, ...pasted]));
    setPasting(false);
  }

  /** Cancelling asks first when there is something to lose (requirement 6.10). */
  function leave() {
    if (unsaved) setAskingToDiscard(true);
    else onClose();
  }

  return (
    <>
      {failure && (
        <p
          id={messageId}
          role="alert"
          className="rounded-md border border-crit px-3 py-2 text-sm text-crit"
        >
          {failure}
        </p>
      )}

      {rows.length === 0 ? (
        <p className="text-muted">{t("catalog.pinout.editor.empty")}</p>
      ) : (
        <table
          aria-label={t("catalog.pinout.editor.table")}
          className="w-full border-collapse text-left"
        >
          <thead>
            <tr className="border-b border-border text-sm text-muted">
              {COLUMNS.map((column) => (
                <th key={column} scope="col" className={`${cell} font-medium`}>
                  {t(`catalog.pinout.columns.${column}`)}
                </th>
              ))}
              <th scope="col" className={`${cell} font-medium`}>
                {t("catalog.pinout.editor.rowActions")}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <PinRow
                key={row.key}
                row={row}
                index={index}
                last={index === rows.length - 1}
                marked={refusal?.row === index + 1 ? refusal.field : null}
                messageId={messageId}
                onEdit={(column, value) => edit(index, column, value)}
                onMove={(by) => setRows((current) => moved(current, index, index + by))}
                onRemove={() => setRows((current) => current.filter((_, at) => at !== index))}
              />
            ))}
          </tbody>
        </table>
      )}

      {rows.length > 0 && (
        <p className="text-sm text-muted">{t("catalog.pinout.editor.functionsHint")}</p>
      )}

      <div className="flex flex-wrap gap-3">
        <button type="button" onClick={addRow} className={action}>
          {t("catalog.pinout.editor.addRow")}
        </button>
        <button type="button" onClick={() => setPasting(true)} className={action}>
          {t("catalog.pinout.editor.openPaste")}
        </button>
      </div>

      {pasting && <PastePanel onApply={applyPaste} onCancel={() => setPasting(false)} />}

      {askingToDiscard ? (
        <fieldset className="grid gap-2">
          <legend className="text-sm">{t("catalog.pinout.editor.discardQuestion")}</legend>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-crit px-4 py-2 text-crit hover:bg-surface-2"
            >
              {t("catalog.pinout.editor.discardConfirm")}
            </button>
            <button
              type="button"
              onClick={() => setAskingToDiscard(false)}
              className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
            >
              {t("catalog.pinout.editor.discardCancel")}
            </button>
          </div>
        </fieldset>
      ) : (
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            disabled={save.isPending}
            onClick={() => save.mutate(replacementOf(rows), { onSuccess: onClose })}
            className="rounded-md bg-primary px-4 py-2 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
          >
            {save.isPending ? t("catalog.pinout.editor.saving") : t("catalog.pinout.editor.save")}
          </button>
          <button
            type="button"
            onClick={leave}
            className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
          >
            {t("catalog.pinout.editor.cancel")}
          </button>
        </div>
      )}
    </>
  );
}

type PinRowProps = {
  row: Row;
  /** 0-based, so the row the owner sees, and the one a refusal names, is `index + 1`. */
  index: number;
  last: boolean;
  /** The cell a refusal named on this row, or null when it named another row or none. */
  marked: PinField | null;
  messageId: string;
  onEdit: (column: PinField, value: string) => void;
  onMove: (by: 1 | -1) => void;
  onRemove: () => void;
};

/**
 * One editable pin. Every cell is named with its row (`Pin 3, label`), because a column
 * header says nothing to a screen reader once forty rows look alike (requirement 6.11), and
 * a refused cell is marked and points at the message that explains it.
 */
function PinRow({ row, index, last, marked, messageId, onEdit, onMove, onRemove }: PinRowProps) {
  const { t } = useTranslation();
  const number = index + 1;
  const markedInput = useRef<HTMLInputElement>(null);
  const markedSelect = useRef<HTMLSelectElement>(null);

  // A refused table lands the keyboard on the cell to fix, which brings it into view too.
  useEffect(() => {
    if (marked !== null) (markedInput.current ?? markedSelect.current)?.focus();
  }, [marked]);

  return (
    <tr className="border-b border-border last:border-0">
      {COLUMNS.map((column) => {
        const wrong = marked === column;
        const named = {
          "aria-label": t(`catalog.pinout.editor.cells.${column}`, { row: number }),
          "aria-invalid": wrong ? true : undefined,
          "aria-describedby": wrong ? messageId : undefined,
        };
        return (
          <td key={column} className={cell}>
            {column === "type" ? (
              <select
                {...named}
                ref={wrong ? markedSelect : null}
                value={row.type}
                onChange={(event) => onEdit("type", event.target.value)}
                className={control}
              >
                {/* What a paste couldn't map keeps its own text, and what it couldn't guess
                    stays empty: both are shown as they are, for the owner to pick (6.5). */}
                {!isPinType(row.type) && (
                  <option value={row.type}>
                    {row.type === "" ? t("catalog.pinout.editor.noType") : row.type}
                  </option>
                )}
                {PIN_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {t(`catalog.pinout.types.${type}`)}
                  </option>
                ))}
              </select>
            ) : (
              <input
                {...named}
                ref={wrong ? markedInput : null}
                type="text"
                value={row[column]}
                onChange={(event) => onEdit(column, event.target.value)}
                className={`${control} font-mono`}
              />
            )}
          </td>
        );
      })}
      <td className={cell}>
        <span className="flex gap-1">
          <button
            type="button"
            className={action}
            disabled={index === 0}
            aria-label={t("catalog.pinout.editor.moveUp", { row: number })}
            onClick={() => onMove(-1)}
          >
            ↑
          </button>
          <button
            type="button"
            className={action}
            disabled={last}
            aria-label={t("catalog.pinout.editor.moveDown", { row: number })}
            onClick={() => onMove(1)}
          >
            ↓
          </button>
          <button
            type="button"
            className={action}
            aria-label={t("catalog.pinout.editor.remove", { row: number })}
            onClick={onRemove}
          >
            ✕
          </button>
        </span>
      </td>
    </tr>
  );
}

/** A stored pin as a row of text. */
function rowOfPin(pin: Pin, index: number): Row {
  return {
    key: `pin-${index}`,
    number: pin.number,
    label: pin.label,
    type: pin.type,
    functions: pin.functions.join(" "),
    // The exact value, not the display form: a pin saved again keeps the volts it had.
    voltage: pin.voltage?.value ?? "",
  };
}

/** A row read from a paste, with its functions back in one cell, separated by spaces. */
function rowOfParsed(parsed: ParsedRow, key: string): Row {
  return {
    key,
    number: parsed.number,
    label: parsed.label,
    type: parsed.type,
    functions: parsed.functions.join(" "),
    voltage: parsed.voltage,
  };
}

function emptyRow(key: string): Row {
  // A select has to show something, and most pins on a board are I/O; a pasted row brings
  // its own type instead, or none when the reader couldn't tell.
  return { key, number: "", label: "", type: "io", functions: "", voltage: "" };
}

/** `rows` with the row at `from` sitting at `to`, or unchanged when `to` is off the table. */
function moved(rows: Row[], from: number, to: number): Row[] {
  const row = rows[from];
  if (row === undefined || to < 0 || to >= rows.length) return rows;
  const rest = rows.filter((_, at) => at !== from);
  return [...rest.slice(0, to), row, ...rest.slice(to)];
}

/**
 * Every cell of every row as one string, which is how an edited table is told from the
 * stored one. The separators are the ASCII ones nothing typed into a cell can hold.
 */
function signature(rows: Row[]): string {
  return rows.map((row) => COLUMNS.map((column) => row[column]).join("\u001f")).join("\u001e");
}

/** The table on the wire: trimmed cells, functions split again, and no level for an empty one. */
function replacementOf(rows: Row[]): PinoutReplacement {
  return {
    pins: rows.map((row) => ({
      number: row.number.trim(),
      label: row.label.trim(),
      type: row.type.trim(),
      functions: row.functions.split(/\s+/).filter((name) => name !== ""),
      voltage: row.voltage.trim() === "" ? null : row.voltage.trim(),
    })),
  };
}
