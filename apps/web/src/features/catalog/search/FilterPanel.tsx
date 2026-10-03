import type { CategoryNode, FacetsResponse, SchemaAttribute } from "@wiredex/api-client";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { FilterBar, FilterField, filterButton, filterControl } from "../../../shared/ui/list";
import { type CategoryBranch, categoryTree } from "../catalog";
import { BoolFilter } from "./BoolFilter";
import { NumberRangeFilter } from "./NumberRangeFilter";
import { OptionsFilter } from "./OptionsFilter";
import { narrows, type PartFilter, type PartQuery, STOCK_FILTERS } from "./searchParams";
import { TextFilter } from "./TextFilter";

type Props = {
  query: PartQuery;
  onChange: (query: PartQuery) => void;
  /** Drops every filter at once; offered while anything narrows the list. */
  onClear: () => void;
  categories: CategoryNode[] | undefined;
  /** The chosen category's resolved schema, once it has loaded; one filter per attribute. */
  attributes: SchemaAttribute[] | undefined;
  facets: FacetsResponse | undefined;
  /** Whether the facets are still loading, so the attribute filters can say so. */
  facetsLoading: boolean;
  /** A refusal message per filter key, shown next to that filter (requirement 6.5). */
  refusals: Record<string, string>;
};

/**
 * The search controls, as one bar above the list: a text box, a category picker (the tree,
 * with an "only this category" option) and a pin box. Choosing a category adds a second row
 * with one filter per attribute of its resolved schema (requirement 6.1), which a button
 * folds away. On a phone the whole bar folds behind a toggle so the results stay readable
 * (requirement 6.7).
 */
export function FilterPanel({
  query,
  onChange,
  onClear,
  categories,
  attributes,
  facets,
  facetsLoading,
  refusals,
}: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [attributesShown, setAttributesShown] = useState(true);
  const panelId = useId();
  const attributesId = useId();
  const textId = useId();
  const categoryId = useId();
  const stockId = useId();
  const manufacturerId = useId();
  const pinId = useId();

  const set = (patch: Partial<PartQuery>) => onChange({ ...query, ...patch });

  /** Replace or drop the filter for one key, leaving the others as they are. */
  const setFilter = (key: string, filter: PartFilter | null) => {
    const rest = query.filters.filter((existing) => existing.key !== key);
    set({ filters: filter ? [...rest, filter] : rest });
  };
  const filterFor = (key: string) => query.filters.find((filter) => filter.key === key);
  const narrowed = narrows(query);

  return (
    <div className="grid gap-2">
      {/* The toggle only shows on a phone; a wider screen keeps the bar open (6.7). */}
      <div className="flex items-center justify-between sm:hidden">
        <h2 className="font-display text-lg font-semibold">{t("catalog.search.filters")}</h2>
        <button
          type="button"
          onClick={() => setOpen((was) => !was)}
          aria-expanded={open}
          aria-controls={panelId}
          className={filterButton}
        >
          {open ? t("catalog.search.hideFilters") : t("catalog.search.showFilters")}
        </button>
      </div>
      <div id={panelId} className={`${open ? "grid" : "hidden"} gap-2 sm:grid`}>
        <FilterBar>
          <FilterField label={t("catalog.search.text")} htmlFor={textId} grow>
            <input
              id={textId}
              type="search"
              value={query.text}
              onChange={(event) => set({ text: event.target.value })}
              placeholder={t("catalog.search.textPlaceholder")}
              className={filterControl}
            />
          </FilterField>
          <FilterField label={t("catalog.search.category")} htmlFor={categoryId}>
            <select
              id={categoryId}
              value={query.category ?? ""}
              onChange={(event) =>
                set({ category: event.target.value || null, filters: [], exact: false })
              }
              className={`${filterControl} sm:w-60`}
            >
              <option value="">{t("catalog.search.everyCategory")}</option>
              {flatten(categoryTree(categories ?? [])).map(({ category, depth }) => (
                <option key={category.id} value={category.id}>
                  {`${"\u00A0\u00A0".repeat(depth)}${category.name}`}
                </option>
              ))}
            </select>
          </FilterField>
          <FilterField label={t("catalog.search.stock")} htmlFor={stockId}>
            <select
              id={stockId}
              value={query.stock ?? ""}
              onChange={(event) =>
                set({ stock: STOCK_FILTERS.find((known) => known === event.target.value) ?? null })
              }
              className={`${filterControl} sm:w-40`}
            >
              <option value="">{t("catalog.search.anyStock")}</option>
              <option value="in_stock">{t("catalog.search.inStock")}</option>
              <option value="out_of_stock">{t("catalog.search.outOfStock")}</option>
            </select>
          </FilterField>
          <FilterField label={t("catalog.search.manufacturer")} htmlFor={manufacturerId}>
            <input
              id={manufacturerId}
              type="text"
              value={query.manufacturer}
              onChange={(event) => set({ manufacturer: event.target.value })}
              placeholder={t("catalog.search.manufacturerPlaceholder")}
              className={`${filterControl} sm:w-44`}
            />
          </FilterField>
          <FilterField label={t("catalog.search.pin")} htmlFor={pinId}>
            <input
              id={pinId}
              type="text"
              value={query.pin}
              onChange={(event) => set({ pin: event.target.value })}
              placeholder={t("catalog.search.pinPlaceholder")}
              className={`${filterControl} font-mono sm:w-44`}
            />
          </FilterField>
          {query.category !== null && (
            <label className="flex h-9 items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={query.exact}
                onChange={(event) => set({ exact: event.target.checked })}
                className="size-4 accent-primary"
              />
              {t("catalog.search.onlyThisCategory")}
            </label>
          )}
          {query.category !== null && (
            <button
              type="button"
              onClick={() => setAttributesShown((was) => !was)}
              aria-expanded={attributesShown}
              aria-controls={attributesId}
              className={filterButton}
            >
              {t("catalog.search.attributes")}
              {query.filters.length > 0 && (
                <span className="rounded-full bg-primary px-1.5 text-xs font-semibold text-on-primary">
                  {query.filters.length}
                </span>
              )}
            </button>
          )}
          {narrowed && (
            <button type="button" onClick={onClear} className={filterButton}>
              {t("catalog.search.clear")}
            </button>
          )}
        </FilterBar>
        {query.category !== null && (
          <div
            id={attributesId}
            className={`${attributesShown ? "grid" : "hidden"} grid-cols-1 gap-x-6 gap-y-3 rounded-lg border border-border bg-surface px-3 py-2.5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4`}
          >
            <h3 className="sr-only">{t("catalog.search.attributes")}</h3>
            {facetsLoading && !facets && (
              <p className="text-sm text-muted">{t("catalog.search.loadingFacets")}</p>
            )}
            {(attributes ?? []).map((attribute) => (
              <AttributeFilter
                key={attribute.id}
                attribute={attribute}
                filter={filterFor(attribute.key)}
                facets={facets}
                refusal={refusals[attribute.key]}
                onChange={(filter) => setFilter(attribute.key, filter)}
              />
            ))}
            {attributes && attributes.length === 0 && (
              <p className="text-sm text-muted">{t("catalog.search.noAttributes")}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

type AttributeFilterProps = {
  attribute: SchemaAttribute;
  filter: PartFilter | undefined;
  facets: FacetsResponse | undefined;
  refusal: string | undefined;
  onChange: (filter: PartFilter | null) => void;
};

/** The one control the attribute's kind calls for (requirement 6.1). */
function AttributeFilter({ attribute, filter, facets, refusal, onChange }: AttributeFilterProps) {
  switch (attribute.kind) {
    case "number":
      return (
        <NumberRangeFilter
          attribute={attribute}
          filter={filter?.type === "range" ? filter : undefined}
          onChange={onChange}
          refusal={refusal}
        />
      );
    case "enum":
      return (
        <OptionsFilter
          attribute={attribute}
          filter={filter?.type === "options" ? filter : undefined}
          onChange={onChange}
          counts={facets?.enums[attribute.key]}
        />
      );
    case "bool":
      return (
        <BoolFilter
          attribute={attribute}
          filter={filter?.type === "bool" ? filter : undefined}
          onChange={onChange}
        />
      );
    case "text":
      return (
        <TextFilter
          attribute={attribute}
          filter={filter?.type === "text" ? filter : undefined}
          onChange={onChange}
        />
      );
  }
}

type Flat = { category: CategoryNode; depth: number };

/** The tree as an indented flat list, so a `<select>` can show the hierarchy in one column. */
function flatten(branches: CategoryBranch[], depth = 0): Flat[] {
  return branches.flatMap((branch) => [
    { category: branch.category, depth },
    ...flatten(branch.children, depth + 1),
  ]);
}
