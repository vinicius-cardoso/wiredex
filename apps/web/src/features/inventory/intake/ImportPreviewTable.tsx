import { Link } from "@tanstack/react-router";
import type {
  CellProblem,
  ImportPreview,
  ImportRow,
  PartOutcome,
  StockOutcome,
} from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { problemText } from "./problems";

/**
 * What a preview says each row will do (requirement 7.2): its number as the spreadsheet shows
 * it, the part it defines or names, the stock it puts away, and every problem found in it,
 * each in the reader's language (11.2). The sheet's own problems, which belong to no row, come
 * first, above the table.
 */
export function ImportPreviewTable({ preview }: { preview: ImportPreview }) {
  const { t } = useTranslation();

  return (
    <div className="grid gap-4">
      {preview.problems.length > 0 && (
        <div className="grid gap-1 rounded-md border border-crit px-3 py-2">
          <h3 className="font-semibold">{t("inventory.import.table.sheetProblems")}</h3>
          <ProblemList problems={preview.problems} />
        </div>
      )}
      {preview.rows.length > 0 && (
        // Positioned, so the sr-only caption (placed absolutely) stays inside this frame instead
        // of widening the scroll range of whatever scrolls above it.
        <div className="relative overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">{t("inventory.import.table.caption")}</caption>
            <thead>
              <tr className="border-b border-border text-muted">
                <th scope="col" className="py-2 pr-4 font-medium">
                  {t("inventory.import.table.row")}
                </th>
                <th scope="col" className="py-2 pr-4 font-medium">
                  {t("inventory.import.table.part")}
                </th>
                <th scope="col" className="py-2 pr-4 font-medium">
                  {t("inventory.import.table.stock")}
                </th>
                <th scope="col" className="py-2 font-medium">
                  {t("inventory.import.table.problems")}
                </th>
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((row) => (
                <PreviewRow key={row.row} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function PreviewRow({ row }: { row: ImportRow }) {
  const { t } = useTranslation();
  return (
    <tr className="border-b border-border align-top">
      <th scope="row" className="py-2 pr-4 font-normal tabular-nums">
        {row.row}
      </th>
      <td className="py-2 pr-4">
        <PartCell part={row.part} />
      </td>
      <td className="py-2 pr-4">
        <StockCell stock={row.stock} />
      </td>
      <td className="py-2">
        {row.problems.length > 0 ? (
          <ProblemList problems={row.problems} />
        ) : (
          <span className="text-muted">{t("inventory.import.table.noProblems")}</span>
        )}
      </td>
    </tr>
  );
}

function PartCell({ part }: { part: PartOutcome }) {
  const { t } = useTranslation();
  const name = part.name ?? t("inventory.import.table.unnamed");

  if (part.kind === "same_as_row") {
    return <span>{t("inventory.import.table.sameAsRow", { row: part.same_as_row ?? 0 })}</span>;
  }
  if (part.kind === "existing") {
    return (
      <div className="grid gap-0.5">
        <span className="text-muted">{t("inventory.import.table.existingPart")}</span>
        {part.part_id ? (
          <Link
            to="/parts/$partId"
            params={{ partId: part.part_id }}
            className="font-semibold text-primary underline"
          >
            {name}
          </Link>
        ) : (
          <span className="font-semibold">{name}</span>
        )}
      </div>
    );
  }
  return (
    <div className="grid gap-0.5">
      <span className="text-muted">{t("inventory.import.table.newPart")}</span>
      <span className="font-semibold">{name}</span>
      {part.category && <span className="text-muted">{part.category}</span>}
    </div>
  );
}

function StockCell({ stock }: { stock: StockOutcome | null }) {
  const { t } = useTranslation();
  if (!stock) return <span className="text-muted">{t("inventory.import.table.noStock")}</span>;

  const labelled = stock.units.filter((unit) => unit.serial !== null || unit.mac !== null);
  return (
    <div className="grid gap-0.5">
      <span className="tabular-nums">
        {stock.kind === "units"
          ? t("inventory.import.table.units", { number: stock.quantity })
          : t("inventory.import.table.lot", { number: stock.quantity })}
      </span>
      <span>
        <span className="font-mono">{stock.location.code}</span> {stock.location.name}
      </span>
      {labelled.map((unit) => (
        <span key={`${unit.serial ?? ""}|${unit.mac ?? ""}`} className="font-mono text-muted">
          {[
            unit.serial !== null ? t("inventory.import.table.serial", { serial: unit.serial }) : "",
            unit.mac !== null ? t("inventory.import.table.mac", { mac: unit.mac }) : "",
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
      ))}
    </div>
  );
}

/** Each problem next to the cell it is about: the column, then what is wrong with it. */
export function ProblemList({ problems }: { problems: readonly CellProblem[] }) {
  const { t } = useTranslation();
  return (
    <ul className="grid gap-1">
      {problems.map((problem, index) => (
        // A row can hold the same code twice (two refused attributes), so the index keys it.
        // biome-ignore lint/suspicious/noArrayIndexKey: the list is never reordered.
        <li key={index} className="text-crit">
          {problem.column && <span className="font-mono">{problem.column}: </span>}
          {problemText(problem, t)}
        </li>
      ))}
    </ul>
  );
}
