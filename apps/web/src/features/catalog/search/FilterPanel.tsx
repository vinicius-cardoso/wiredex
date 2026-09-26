import type { CategoryNode, FacetsResponse, SchemaAttribute } from "@wiredex/api-client";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { type CategoryBranch, categoryTree } from "../catalog";
import { BoolFilter } from "./BoolFilter";
import { NumberRangeFilter } from "./NumberRangeFilter";
import { OptionsFilter } from "./OptionsFilter";
import type { PartFilter, PartQuery } from "./searchParams";
import { TextFilter } from "./TextFilter";

const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";

type Props = {
  query: PartQuery;
  onChange: (query: PartQuery) => void;
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
 * The search controls: a text box, a category picker (the tree, with an "only this category"
 * option), a pin box, and one filter per attribute of the chosen category's resolved schema
 * (requirement 6.1). On a phone the whole panel folds behind a toggle so the results stay
 * readable (requirement 6.7); on a wide screen it is always open.
 */
export function FilterPanel({
  query,
  onChange,
  categories,
  attributes,
  facets,
  facetsLoading,
  refusals,
}: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const textId = useId();
  const categoryId = useId();
  const pinId = useId();

  const set = (patch: Partial<PartQuery>) => onChange({ ...query, ...patch });

  /** Replace or drop the filter for one key, leaving the others as they are. */
  const setFilter = (key: string, filter: PartFilter | null) => {
    const rest = query.filters.filter((existing) => existing.key !== key);
    set({ filters: filter ? [...rest, filter] : rest });
  };
  const filterFor = (key: string) => query.filters.find((filter) => filter.key === key);

  return (
    <search className="grid gap-3 rounded-lg border border-border bg-surface p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg font-semibold">{t("catalog.search.filters")}</h2>
        {/* The toggle only shows on a phone; a wide screen keeps the panel open (6.7). */}
        <button
          type="button"
          onClick={() => setOpen((was) => !was)}
          aria-expanded={open}
          aria-controls={panelId}
          className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2 sm:hidden"
        >
          {open ? t("catalog.search.hideFilters") : t("catalog.search.showFilters")}
        </button>
      </div>

      <div id={panelId} className={`${open ? "grid" : "hidden"} gap-3 sm:grid`}>
        <div className="grid gap-1">
          <label htmlFor={textId} className="text-sm font-medium">
            {t("catalog.search.text")}
          </label>
          <input
            id={textId}
            type="search"
            value={query.text}
            onChange={(event) => set({ text: event.target.value })}
            placeholder={t("catalog.search.textPlaceholder")}
            className={control}
          />
        </div>

        <div className="grid gap-1">
          <label htmlFor={categoryId} className="text-sm font-medium">
            {t("catalog.search.category")}
          </label>
          <select
            id={categoryId}
            value={query.category ?? ""}
            onChange={(event) =>
              set({ category: event.target.value || null, filters: [], exact: false })
            }
            className={control}
          >
            <option value="">{t("catalog.search.everyCategory")}</option>
            {flatten(categoryTree(categories ?? [])).map(({ category, depth }) => (
              <option key={category.id} value={category.id}>
                {`${"\u00A0\u00A0".repeat(depth)}${category.name}`}
              </option>
            ))}
          </select>
          {query.category !== null && (
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={query.exact}
                onChange={(event) => set({ exact: event.target.checked })}
                className="size-4 accent-primary"
              />
              {t("catalog.search.onlyThisCategory")}
            </label>
          )}
        </div>

        <div className="grid gap-1">
          <label htmlFor={pinId} className="text-sm font-medium">
            {t("catalog.search.pin")}
          </label>
          <input
            id={pinId}
            type="text"
            value={query.pin}
            onChange={(event) => set({ pin: event.target.value })}
            placeholder={t("catalog.search.pinPlaceholder")}
            className={`${control} font-mono`}
          />
        </div>

        {query.category !== null && (
          <div className="grid gap-3 border-t border-border pt-3">
            <h3 className="text-sm font-semibold text-muted">{t("catalog.search.attributes")}</h3>
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
          </div>
        )}
      </div>
    </search>
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
