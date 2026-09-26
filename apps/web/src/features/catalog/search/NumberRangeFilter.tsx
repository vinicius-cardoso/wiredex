import type { SchemaAttribute } from "@wiredex/api-client";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { formatSi, parseSi } from "../notation";

const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";

type RangeFilter = { type: "range"; key: string; minimum: string | null; maximum: string | null };

type Props = {
  attribute: SchemaAttribute;
  /** The current range for this attribute, if the owner has typed one. */
  filter: RangeFilter | undefined;
  /** The new range, or null when both bounds are empty and the filter is dropped. */
  onChange: (filter: RangeFilter | null) => void;
  /** What the API said when it refused this filter, shown under the field (requirement 6.5). */
  refusal?: string | undefined;
};

/**
 * A minimum and a maximum for a number attribute (requirement 6.1). Each bound is typed as
 * it is printed on a part — `1k`, `4k7` — and the normalized value shows beside it as it is
 * typed, the same preview the part form has, so the owner sees `1k` read as `1kΩ` before the
 * search runs. An empty pair drops the filter; either bound alone keeps it.
 */
export function NumberRangeFilter({ attribute, filter, onChange, refusal }: Props) {
  const { t } = useTranslation();
  const minId = useId();
  const maxId = useId();
  const refusalId = useId();

  const minimum = filter?.minimum ?? "";
  const maximum = filter?.maximum ?? "";

  function change(nextMin: string, nextMax: string) {
    const min = nextMin.trim() === "" ? null : nextMin;
    const max = nextMax.trim() === "" ? null : nextMax;
    if (min === null && max === null) onChange(null);
    else onChange({ type: "range", key: attribute.key, minimum: min, maximum: max });
  }

  return (
    <fieldset className="grid grid-cols-1 gap-1" aria-invalid={refusal ? true : undefined}>
      <legend className="text-sm font-medium">
        {attribute.label}
        {attribute.unit ? ` (${attribute.unit})` : ""}
      </legend>
      <div className="flex flex-wrap gap-2">
        <Bound
          id={minId}
          label={t("catalog.search.range.min", { label: attribute.label })}
          value={minimum}
          unit={attribute.unit}
          describedBy={refusal ? refusalId : undefined}
          onChange={(value) => change(value, maximum)}
        />
        <Bound
          id={maxId}
          label={t("catalog.search.range.max", { label: attribute.label })}
          value={maximum}
          unit={attribute.unit}
          describedBy={refusal ? refusalId : undefined}
          onChange={(value) => change(minimum, value)}
        />
      </div>
      {refusal && (
        <p id={refusalId} role="alert" className="text-sm text-crit">
          {refusal}
        </p>
      )}
    </fieldset>
  );
}

type BoundProps = {
  id: string;
  label: string;
  value: string;
  unit: string | null;
  describedBy: string | undefined;
  onChange: (value: string) => void;
};

function Bound({ id, label, value, unit, describedBy, onChange }: BoundProps) {
  const { t } = useTranslation();
  const previewId = `${id}-preview`;
  const preview = previewOf(value, unit);
  const described =
    [preview ? previewId : null, describedBy].filter(Boolean).join(" ") || undefined;

  return (
    <span className="grid gap-1">
      <label htmlFor={id} className="text-xs text-muted">
        {label}
      </label>
      <input
        id={id}
        type="text"
        inputMode="decimal"
        value={value}
        // The bound is typed as it prints on a part: "4k7", not "0.0047".
        onChange={(event) => onChange(event.target.value)}
        {...(described ? { "aria-describedby": described } : {})}
        className={`${control} w-28`}
      />
      {preview && (
        <span id={previewId} className="text-xs text-muted">
          {t("catalog.search.range.preview", { value: preview })}
        </span>
      )}
    </span>
  );
}

/** The normalized value to show beside a bound, or null for what can't be read yet. */
function previewOf(value: string, unit: string | null): string | null {
  if (value.trim() === "") return null;
  const parsed = parseSi(value, unit);
  return parsed === null ? null : formatSi(parsed, unit);
}
