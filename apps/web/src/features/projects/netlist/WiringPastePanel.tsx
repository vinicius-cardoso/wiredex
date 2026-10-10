import { useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { StackedTable } from "../../../shared/ui/block";
import { refusalOf } from "./netFields";
import { NetRefusal, usePasteNets } from "./netlist";
import { MOST_LINES, parseWiring, type WiringRow } from "./paste";
import { WireSwatch } from "./WireSwatch";

const cell = "py-1 pr-3 align-top last:pr-0";

/**
 * Pasting wiring: the text as it was pasted, the lines it was read as, and one button that
 * adds them all.
 *
 * The API takes the lines whole or not at all, so a refused line leaves the wiring as it was;
 * the panel then says which line of the paste it was and why, and keeps the text to be fixed.
 */
export function WiringPastePanel({
  revisionId,
  onDone,
}: {
  revisionId: string;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const headingId = useId();
  const textId = useId();
  const paste = usePasteNets();
  const [text, setText] = useState("");
  const [refusal, setRefusal] = useState<string | null>(null);
  const { between, rows } = useMemo(() => parseWiring(text), [text]);
  const nothing = rows.length === 0;
  const tooMany = rows.length > MOST_LINES;
  const unread = rows.some((row) => row.problem !== null);

  function apply() {
    setRefusal(null);
    paste.mutate(
      {
        revisionId,
        rows: rows.map((row) => ({
          pins: row.pins,
          name: row.name,
          color: row.color,
          notes: row.notes,
        })),
      },
      {
        onSuccess: onDone,
        onError: (error) => {
          const { fields, row } = refusalOf(t, error, t("projects.netlist.paste.error"));
          const problem = row ?? Object.values(fields)[0] ?? t("projects.netlist.paste.error");
          // The API counts the rows it was sent; the reader counts the lines of the paste.
          const line = error instanceof NetRefusal && error.row ? rows[error.row - 1]?.line : null;
          setRefusal(line ? t("projects.netlist.paste.refusedAt", { line, problem }) : problem);
        },
      },
    );
  }

  return (
    <section
      aria-labelledby={headingId}
      className="grid gap-3 rounded-lg border border-border bg-surface-2 p-4"
    >
      <h4 id={headingId} className="font-semibold">
        {t("projects.netlist.paste.title")}
      </h4>

      <div className="grid gap-1">
        <label htmlFor={textId} className="text-sm font-medium">
          {t("projects.netlist.paste.label")}
        </label>
        <textarea
          id={textId}
          rows={6}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setRefusal(null);
          }}
          className="rounded-md border border-border-strong bg-surface px-3 py-2 font-mono text-sm text-text"
        />
        <p className="text-sm text-muted">{t("projects.netlist.paste.hint")}</p>
      </div>

      {nothing ? (
        <p className="text-muted">{t("projects.netlist.paste.nothing")}</p>
      ) : (
        <>
          <p className="text-sm text-muted">
            {between &&
              `${t("projects.netlist.paste.between", { from: between[0], to: between[1] })} `}
            {t("projects.netlist.paste.rows", { lines: rows.length })}
          </p>
          <Preview rows={rows} />
        </>
      )}

      {unread && <p className="text-sm text-warn">{t("projects.netlist.paste.fix")}</p>}
      {tooMany && (
        <p className="text-sm text-warn">{t("projects.netlist.refusal.too_many_rows")}</p>
      )}
      {refusal && (
        <p role="alert" className="text-sm text-crit">
          {refusal} {t("projects.netlist.paste.nothingSaved")}
        </p>
      )}

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={nothing || unread || tooMany || paste.isPending}
          onClick={apply}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {t(paste.isPending ? "projects.netlist.paste.applying" : "projects.netlist.paste.apply")}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
        >
          {t("projects.netlist.paste.cancel")}
        </button>
      </div>
    </section>
  );
}

/** The lines as they were read, each with what stops it from being sent, if anything does. */
function Preview({ rows }: { rows: WiringRow[] }) {
  const { t } = useTranslation();
  const columns = {
    line: t("projects.netlist.paste.line"),
    name: t("projects.netlist.columns.name"),
    color: t("projects.netlist.columns.color"),
    pins: t("projects.netlist.columns.pins"),
    notes: t("projects.netlist.columns.notes"),
  };

  return (
    <StackedTable below="md">
      <table
        aria-label={t("projects.netlist.paste.preview")}
        className="w-full border-collapse text-left text-sm"
      >
        <thead>
          <tr className="border-b border-border text-muted">
            {Object.entries(columns).map(([column, name]) => (
              <th key={column} scope="col" className={`${cell} font-medium`}>
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.line} className="border-b border-border last:border-0">
              <td data-label={columns.line} className={`${cell} tabular-nums text-muted`}>
                {row.line}
              </td>
              <td data-label={columns.name} className={`${cell} font-mono`}>
                {row.name ?? (
                  <span className="font-sans text-muted">
                    {t("projects.netlist.paste.unnamed")}
                  </span>
                )}
              </td>
              <td data-label={columns.color} className={cell}>
                <WireSwatch color={row.color} />
              </td>
              <td data-label={columns.pins} className={`${cell} font-mono`}>
                {row.problem ? (
                  <span className="font-sans text-warn">
                    {t(`projects.netlist.paste.problems.${row.problem}`)}
                  </span>
                ) : (
                  row.pins
                )}
              </td>
              <td data-label={columns.notes} className={cell}>
                {row.notes ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </StackedTable>
  );
}
