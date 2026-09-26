import type { SchemaAttribute } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";

type BoolFilter = { type: "bool"; key: string; value: boolean };

type Props = {
  attribute: SchemaAttribute;
  /** The current choice, if the owner has set one; absent means "any". */
  filter: BoolFilter | undefined;
  /** True, false, or null for "any", which drops the filter. */
  onChange: (filter: BoolFilter | null) => void;
};

type Choice = "any" | "yes" | "no";

/**
 * A three-way choice for a boolean attribute (requirement 6.1): any, yes, or no. "Any" drops
 * the filter, so the attribute stops narrowing. A radio group, so a screen reader announces
 * the three as one control and the arrow keys move between them.
 */
export function BoolFilter({ attribute, filter, onChange }: Props) {
  const { t } = useTranslation();
  const current: Choice = filter === undefined ? "any" : filter.value ? "yes" : "no";

  function choose(choice: Choice) {
    if (choice === "any") onChange(null);
    else onChange({ type: "bool", key: attribute.key, value: choice === "yes" });
  }

  return (
    <fieldset className="grid gap-1">
      <legend className="text-sm font-medium">{attribute.label}</legend>
      <div className="flex flex-wrap gap-3">
        {(["any", "yes", "no"] as const).map((choice) => (
          <label key={choice} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name={`bool-${attribute.key}`}
              checked={current === choice}
              onChange={() => choose(choice)}
              className="size-4 accent-primary"
            />
            {t(`catalog.search.bool.${choice}`)}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
