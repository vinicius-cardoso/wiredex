import type { SchemaAttribute } from "@wiredex/api-client";
import { useId } from "react";
import { type UseFormReturn, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { formatSi, parseSi } from "./notation";
import type { PartFormValues } from "./PartForm";

const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";

type Props = {
  attribute: SchemaAttribute;
  form: UseFormReturn<PartFormValues>;
  /** Set when the stored value no longer fits this field, so it can be marked to fix. */
  problem?: string | undefined;
};

/**
 * One field, shaped by the attribute's kind (requirement 7.2): a text box with the unit for
 * `number`, a select for `enum`, a text box for `text`, a switch for `bool`. The label is the
 * field's accessible name on its own; the unit, the notation preview and any message are
 * descriptions, so a screen reader hears them without them becoming part of the name.
 */
export function AttributeField({ attribute, form, problem }: Props) {
  const { t } = useTranslation();
  const id = useId();
  const name = `attributes.${attribute.key}` as const;
  const error = form.formState.errors.attributes?.[attribute.key]?.message;
  const message = error ?? problem;
  const unitId = `${id}-unit`;
  const previewId = `${id}-preview`;
  const messageId = `${id}-message`;

  const typed = useWatch({ control: form.control, name });
  const preview = attribute.kind === "number" ? previewOf(typed, attribute.unit) : null;
  const describedBy =
    [attribute.unit ? unitId : null, preview ? previewId : null, message ? messageId : null]
      .filter(Boolean)
      .join(" ") || undefined;

  return (
    <div className="grid gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {attribute.label}
      </label>
      <div className="flex flex-wrap items-center gap-2">
        {attribute.kind === "bool" && (
          <input
            id={id}
            type="checkbox"
            role="switch"
            aria-checked={typed === true}
            className="size-5 accent-primary"
            {...form.register(name)}
          />
        )}
        {attribute.kind === "enum" && (
          <select
            id={id}
            className={control}
            aria-required={attribute.required}
            aria-invalid={message ? true : undefined}
            {...(describedBy ? { "aria-describedby": describedBy } : {})}
            {...form.register(name)}
          >
            <option value="">{t("catalog.form.noChoice")}</option>
            {attribute.options.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        )}
        {(attribute.kind === "number" || attribute.kind === "text") && (
          <input
            id={id}
            type="text"
            className={control}
            // The value is typed as it is printed on the part: "4k7", not "0.0047".
            {...(attribute.kind === "number" ? { inputMode: "decimal" as const } : {})}
            aria-required={attribute.required}
            aria-invalid={message ? true : undefined}
            {...(describedBy ? { "aria-describedby": describedBy } : {})}
            {...form.register(name)}
          />
        )}
        {attribute.unit && (
          <span id={unitId} className="text-sm text-muted">
            {attribute.unit}
          </span>
        )}
        {preview && (
          <span id={previewId} className="text-sm text-muted">
            {t("catalog.form.preview", { value: preview })}
          </span>
        )}
      </div>
      {message && (
        <p id={messageId} className="text-sm text-crit">
          {message}
        </p>
      )}
    </div>
  );
}

/**
 * The normalized value to show beside the field while it is being typed (requirement 7.3).
 * Nothing is shown for what can't be read yet, and the input itself is never rewritten.
 */
function previewOf(value: string | boolean | undefined, unit: string | null): string | null {
  if (typeof value !== "string" || value.trim() === "") return null;
  const parsed = parseSi(value, unit);
  return parsed === null ? null : formatSi(parsed, unit);
}
