import type { TFunction } from "i18next";
import { useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { type ParsedRow, parsePinTable } from "./paste";
import { isPinType } from "./pinTypes";

const COLUMNS = ["number", "label", "type", "functions", "voltage"] as const;
const cell = "py-1 pr-3 align-top last:pr-0";

/** What the read rows do to the table they land in (requirement 6.8). */
export type PasteMode = "replace" | "append";

/**
 * A read row and the line it came from. A pasted table may repeat a number or hold none at
 * all, so where a row sat in the paste is the only thing that tells it from the next one.
 */
type PreviewRow = ParsedRow & { key: string };

type PastePanelProps = {
  onApply: (rows: ParsedRow[], mode: PasteMode) => void;
  onCancel: () => void;
};

/**
 * Pasting a pin table: the text as it was pasted, the rows it was read as, and two ways to
 * take them (requirements 6.2, 6.8).
 *
 * Nothing here saves, and nothing here changes the table on its own: the rows are shown
 * first, marked with whatever had to be interpreted, and a click takes them into the editor
 * — which is still only a table until it is saved.
 */
export function PastePanel({ onApply, onCancel }: PastePanelProps) {
  const { t } = useTranslation();
  const headingId = useId();
  const textId = useId();
  const [text, setText] = useState("");
  const rows = useMemo<PreviewRow[]>(
    () => parsePinTable(text).map((row, at) => ({ ...row, key: `line-${at}` })),
    [text],
  );
  const nothing = rows.length === 0;

  return (
    <section
      aria-labelledby={headingId}
      className="grid gap-3 rounded-lg border border-border bg-surface-2 p-4"
    >
      <h3 id={headingId} className="font-semibold">
        {t("catalog.pinout.paste.title")}
      </h3>

      <div className="grid gap-1">
        <label htmlFor={textId} className="text-sm font-medium">
          {t("catalog.pinout.paste.label")}
        </label>
        <textarea
          id={textId}
          rows={6}
          value={text}
          onChange={(event) => setText(event.target.value)}
          className="rounded-md border border-border-strong bg-surface px-3 py-2 font-mono text-sm text-text"
        />
        <p className="text-sm text-muted">{t("catalog.pinout.paste.hint")}</p>
      </div>

      {nothing ? (
        <p className="text-muted">{t("catalog.pinout.paste.nothing")}</p>
      ) : (
        <>
          <p className="text-sm text-muted">
            {t("catalog.pinout.paste.rows", { lines: rows.length })}
          </p>
          <Preview rows={rows} />
        </>
      )}

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={nothing}
          onClick={() => onApply(rows, "replace")}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {t("catalog.pinout.paste.replace")}
        </button>
        <button
          type="button"
          disabled={nothing}
          onClick={() => onApply(rows, "append")}
          className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2 disabled:opacity-60"
        >
          {t("catalog.pinout.paste.append")}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
        >
          {t("catalog.pinout.paste.cancel")}
        </button>
      </div>
    </section>
  );
}

/** The rows as they were read, each carrying whatever the reader had to interpret. */
function Preview({ rows }: { rows: PreviewRow[] }) {
  const { t } = useTranslation();

  return (
    <table
      aria-label={t("catalog.pinout.paste.preview")}
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
            {t("catalog.pinout.paste.notes")}
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.key} className="border-b border-border last:border-0">
            <td className={`${cell} font-mono tabular-nums`}>{row.number || "—"}</td>
            <td className={`${cell} font-mono`}>{row.label || "—"}</td>
            <td className={cell}>{typeName(row.type, t)}</td>
            <td className={`${cell} font-mono text-sm`}>{row.functions.join(" ") || "—"}</td>
            <td className={`${cell} tabular-nums`}>{row.voltage || "—"}</td>
            <td className={`${cell} text-sm text-warn`}>
              {row.warnings.map((warning) => t(`catalog.pinout.paste.${warning}`)).join(" ")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** One of the eight, in words; anything else exactly as it was pasted (requirement 6.5). */
function typeName(type: string, t: TFunction): string {
  return isPinType(type) ? t(`catalog.pinout.types.${type}`) : type || "—";
}
