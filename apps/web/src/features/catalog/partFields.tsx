import { zodResolver } from "@hookform/resolvers/zod";
import type { AttributeValue, CategoryNode, SchemaAttribute } from "@wiredex/api-client";
import type { TFunction } from "i18next";
import { type ChangeEvent, useId } from "react";
import type { Resolver, UseFormReturn } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { parseSi } from "./notation";

/**
 * The part half of a form, shared by the part form and quick-add, so both read one set of
 * rules: the category choice, the four detail fields, the Zod schema built from a category's
 * resolved fields, and how the values become a request.
 */

/** The API's own cap on a text attribute, checked here so the form says so first. */
const MAX_TEXT_LENGTH = 500;

const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";

/** What the fields hold. Attribute values are keyed by attribute key, as the API keys them. */
export type PartFormValues = {
  categoryId: string;
  name: string;
  manufacturer: string;
  mpn: string;
  package: string;
  attributes: Record<string, string | boolean>;
};

export type DetailName = "name" | "manufacturer" | "mpn" | "package";

type ChoiceProps = {
  form: UseFormReturn<PartFormValues>;
  categories: CategoryNode[];
  onPicked: (categoryId: string) => void;
};

export function CategoryChoice({ form, categories, onPicked }: ChoiceProps) {
  const { t } = useTranslation();
  const id = useId();
  const error = form.formState.errors.categoryId?.message;

  return (
    <div className="grid gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {t("catalog.form.category")}
      </label>
      <select
        id={id}
        className={control}
        aria-required={true}
        aria-invalid={error ? true : undefined}
        {...(error ? { "aria-describedby": `${id}-error` } : {})}
        {...form.register("categoryId", {
          onChange: (event: ChangeEvent<HTMLSelectElement>) => onPicked(event.target.value),
        })}
      >
        <option value="">{t("catalog.form.chooseCategory")}</option>
        {categories.map((category) => (
          <option key={category.id} value={category.id}>
            {category.name}
          </option>
        ))}
      </select>
      {error && (
        <p id={`${id}-error`} className="text-sm text-crit">
          {error}
        </p>
      )}
    </div>
  );
}

type DetailProps = { name: DetailName; label: string; form: UseFormReturn<PartFormValues> };

export function DetailField({ name, label, form }: DetailProps) {
  const id = useId();
  const error = form.formState.errors[name]?.message;

  return (
    <div className="grid gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        type="text"
        className={control}
        aria-required={name === "name"}
        aria-invalid={error ? true : undefined}
        {...(error ? { "aria-describedby": `${id}-error` } : {})}
        {...form.register(name)}
      />
      {error && (
        <p id={`${id}-error`} className="text-sm text-crit">
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * Stored values as their fields hold them: a number comes back as engineering notation, so
 * editing or duplicating a 4700 Ω resistor starts from `4.7k` rather than from the zeros.
 */
export function storedValues(
  stored: Record<string, AttributeValue>,
): Record<string, string | boolean> {
  const values: Record<string, string | boolean> = {};
  for (const [key, value] of Object.entries(stored)) {
    values[key] = typeof value.value === "boolean" ? value.value : value.display;
  }
  return values;
}

/**
 * Only the keys this category defines, and only the ones with something in them: an empty
 * optional field is a value nobody entered, not an empty string.
 */
export function sentAttributes(
  values: Record<string, string | boolean>,
  attributes: SchemaAttribute[],
): Record<string, string | boolean> {
  const sending: Record<string, string | boolean> = {};
  for (const attribute of attributes) {
    const value = values[attribute.key];
    if (typeof value === "boolean") sending[attribute.key] = value;
    else if (value !== undefined && value.trim() !== "") sending[attribute.key] = value.trim();
  }
  return sending;
}

/** A detail as the API takes it: trimmed, and null when nothing was typed. */
export function filled(value: string): string | null {
  return value.trim() === "" ? null : value.trim();
}

export function partResolver(
  attributes: SchemaAttribute[],
  t: TFunction,
): Resolver<PartFormValues> {
  // The schema is built from the fetched fields, so its shape isn't known at compile time;
  // the values it hands back are the form's own, untouched.
  return zodResolver(partSchema(attributes, t)) as Resolver<PartFormValues>;
}

function partSchema(attributes: SchemaAttribute[], t: TFunction) {
  const shape: Record<string, z.ZodType> = {};
  for (const attribute of attributes) shape[attribute.key] = fieldSchema(attribute, t);

  return z.object({
    categoryId: required(t("catalog.form.error.chooseCategory")),
    name: required(t("catalog.form.error.required")),
    manufacturer: z.string(),
    mpn: z.string(),
    package: z.string(),
    attributes: z.object(shape),
  });
}

function required(message: string): z.ZodType<string> {
  return z.string().superRefine((value, ctx) => {
    if (value.trim() === "") ctx.addIssue(message);
  });
}

/**
 * The rules one field answers to, by kind. `unknown` is what comes in, because a field of a
 * category picked a moment ago may not have been registered yet.
 */
function fieldSchema(attribute: SchemaAttribute, t: TFunction): z.ZodType {
  return z.unknown().superRefine((raw, ctx) => {
    // A switch is always one of its two answers, so a bool is never missing.
    if (attribute.kind === "bool") return;
    const value = typeof raw === "string" ? raw.trim() : "";
    if (value === "") {
      if (attribute.required) ctx.addIssue(t("catalog.form.error.required"));
      return;
    }
    if (attribute.kind === "number" && parseSi(value, attribute.unit) === null) {
      ctx.addIssue(t("catalog.form.error.badNumber"));
    }
    if (attribute.kind === "enum" && !attribute.options.includes(value)) {
      ctx.addIssue(t("catalog.form.error.notAnOption"));
    }
    if (attribute.kind === "text" && value.length > MAX_TEXT_LENGTH) {
      ctx.addIssue(t("catalog.form.error.tooLong", { max: MAX_TEXT_LENGTH }));
    }
  });
}
