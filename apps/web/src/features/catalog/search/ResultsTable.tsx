import { Link } from "@tanstack/react-router";
import type { CategoryNode, SchemaAttribute, SearchResult } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { listCell, listHead, listRow, listTable, TableFrame } from "../../../shared/ui/list";
import { categoryName } from "../catalog";
import type { SortDirection, SortField } from "./searchParams";

const cell = listCell;

type Props = {
  results: SearchResult[];
  categories: CategoryNode[] | undefined;
  /** The chosen category's number and enum attributes, which become the extra columns. */
  attributes: SchemaAttribute[];
  /**
   * Each shown part's total on_hand, keyed by id, from the batch totals route (requirement
   * 7.1). A part missing from the map has no stock, so it reads as zero.
   */
  totals: Map<string, number> | undefined;
  sort: SortField;
  direction: SortDirection;
  /** Clicking a sortable header: name, or a number attribute. Enum columns don't sort. */
  onSort: (sort: SortField) => void;
  /** The page on show; a new one scrolls the table back to its first row. */
  scrollKey?: string;
};

/**
 * The results, with name, category and part number, then a column per number and enum
 * attribute of the chosen category (requirement 6.3). The name and the number-attribute
 * headers are buttons that sort, and carry `aria-sort` so a screen reader announces the
 * order; clicking the active one flips the direction. The table scrolls sideways on a narrow
 * screen so the page itself doesn't (requirement 6.7).
 */
export function ResultsTable({
  results,
  categories,
  attributes,
  totals,
  sort,
  direction,
  onSort,
  scrollKey,
}: Props) {
  const { t } = useTranslation();
  const columns = attributes.filter(
    (attribute) => attribute.kind === "number" || attribute.kind === "enum",
  );

  return (
    <TableFrame scrollKey={scrollKey}>
      <table className={listTable}>
        <caption className="sr-only">{t("catalog.search.list")}</caption>
        <thead className={listHead}>
          <tr>
            <SortableHeader
              label={t("catalog.search.columns.name")}
              field="name"
              sort={sort}
              direction={direction}
              onSort={onSort}
            />
            <th scope="col" className={`${cell} font-medium`}>
              {t("catalog.search.columns.category")}
            </th>
            <th scope="col" className={`${cell} font-medium`}>
              {t("catalog.search.columns.manufacturer")}
            </th>
            <th scope="col" className={`${cell} font-medium`}>
              {t("catalog.search.columns.mpn")}
            </th>
            <th scope="col" className={`${cell} font-medium`}>
              {t("catalog.search.columns.package")}
            </th>
            <th scope="col" className={`${cell} font-medium`}>
              {t("catalog.search.columns.stock")}
            </th>
            {columns.map((attribute) =>
              attribute.kind === "number" ? (
                <SortableHeader
                  key={attribute.id}
                  label={attribute.label}
                  field={{ attribute: attribute.key }}
                  sort={sort}
                  direction={direction}
                  onSort={onSort}
                />
              ) : (
                <th key={attribute.id} scope="col" className={`${cell} font-medium`}>
                  {attribute.label}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {results.map((part) => (
            <tr key={part.id} className={listRow}>
              <th scope="row" className={`${cell} font-medium`}>
                <Link
                  to="/parts/$partId"
                  params={{ partId: part.id }}
                  className="text-primary hover:underline"
                >
                  {part.name}
                </Link>
              </th>
              <td className={cell}>{categoryName(categories, part.category_id) ?? blank}</td>
              <td className={cell}>{part.manufacturer ?? blank}</td>
              <td className={`${cell} font-mono`}>{part.mpn ?? blank}</td>
              <td className={`${cell} text-muted`}>{part.package ?? blank}</td>
              <td className={cell}>{totals?.get(part.id) ?? 0}</td>
              {columns.map((attribute) => (
                <td key={attribute.id} className={cell}>
                  {cellValue(part, attribute)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </TableFrame>
  );
}

type HeaderProps = {
  label: string;
  field: SortField;
  sort: SortField;
  direction: SortDirection;
  onSort: (sort: SortField) => void;
};

function SortableHeader({ label, field, sort, direction, onSort }: HeaderProps) {
  const { t } = useTranslation();
  const active = sameField(sort, field);
  const ariaSort = active ? (direction === "asc" ? "ascending" : "descending") : "none";
  const name =
    typeof field === "string"
      ? t("catalog.search.sort.byName")
      : t("catalog.search.sort.byAttribute", { label });

  return (
    <th scope="col" aria-sort={ariaSort} className={`${cell} font-medium`}>
      <button
        type="button"
        // Clicking the active column flips it; a new column starts ascending.
        onClick={() => onSort(field)}
        aria-label={`${name} (${t(`catalog.search.sort.${ariaSort === "none" ? "none" : direction}`)})`}
        className="flex items-center gap-1 hover:text-text"
      >
        {label}
        <span aria-hidden="true">{active ? (direction === "asc" ? "▲" : "▼") : ""}</span>
      </button>
    </th>
  );
}

function sameField(a: SortField, b: SortField): boolean {
  if (typeof a === "string" || typeof b === "string") return a === b;
  return a.attribute === b.attribute;
}

/** The value of one attribute for a part, shown as the API formatted it, or a dash. */
function cellValue(part: SearchResult, attribute: SchemaAttribute): string {
  const value = part.attributes[attribute.key];
  if (!value) return blank;
  const display = value.display;
  return value.unit ? `${display}${value.unit}` : display;
}

/** An em dash for what a part doesn't carry: the same in both languages, so not a key. */
const blank = "—";
