import type { EnumCount, SchemaAttribute } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";

type OptionsFilter = { type: "options"; key: string; options: string[] };

type Props = {
  attribute: SchemaAttribute;
  /** The options the owner has ticked, if any. */
  filter: OptionsFilter | undefined;
  /** The new set, or null when nothing is ticked and the filter is dropped. */
  onChange: (filter: OptionsFilter | null) => void;
  /** How many parts hold each option, from the facets, so a dead option reads as `(0)`. */
  counts: EnumCount[] | undefined;
};

/**
 * A checkbox per enum option, each with how many parts hold it (requirement 6.1). The list
 * comes from the schema, so every defined option is offered; the count comes from the facets
 * and is 0 when nothing has it. Ticking none drops the filter.
 */
export function OptionsFilter({ attribute, filter, onChange, counts }: Props) {
  const { t } = useTranslation();
  const chosen = new Set(filter?.options ?? []);
  const countOf = (option: string) => counts?.find((entry) => entry.option === option)?.count ?? 0;

  function toggle(option: string, on: boolean) {
    const next = new Set(chosen);
    if (on) next.add(option);
    else next.delete(option);
    const options = attribute.options.filter((value) => next.has(value));
    onChange(options.length === 0 ? null : { type: "options", key: attribute.key, options });
  }

  return (
    <fieldset className="grid grid-cols-1 gap-1">
      <legend className="text-sm font-medium">{attribute.label}</legend>
      <div className="grid grid-cols-1 gap-1">
        {attribute.options.map((option) => (
          <label key={option} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={chosen.has(option)}
              onChange={(event) => toggle(option, event.target.checked)}
              className="size-4 accent-primary"
            />
            {t("catalog.search.options.count", { option, count: countOf(option) })}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
