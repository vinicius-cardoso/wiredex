import { useNavigate } from "@tanstack/react-router";
import type { NewPart, PartDetails, SchemaAttribute } from "@wiredex/api-client";
import type { TFunction } from "i18next";
import { useMemo, useState } from "react";
import { type UseFormReturn, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { AttributeField } from "./AttributeField";
import {
  CatalogRefusal,
  useCategories,
  useCategorySchema,
  useDefinePart,
  useUpdatePart,
} from "./catalog";
import {
  CategoryChoice,
  DetailField,
  filled,
  type PartFormValues,
  partResolver,
  sentAttributes,
  storedValues,
} from "./partFields";
import { problemsByKey } from "./review";

type Props = {
  /** The part being edited. Absent means a new one. */
  part?: PartDetails;
  onSaved: (part: PartDetails) => void;
  onCancel?: () => void;
};

/**
 * The part form, its attribute half built from the category's schema (requirement 7.2).
 *
 * Picking a category fetches that category's resolved schema and the fields follow; the Zod
 * schema is rebuilt from the same response, so a missing required value or a number nobody
 * can read is caught before a request goes out (requirement 7.4). The API validates again
 * regardless, and what it refuses lands on the field it names (requirement 7.5).
 */
export function PartForm({ part, onSaved, onCancel }: Props) {
  const { t } = useTranslation();
  const categories = useCategories();
  const define = useDefinePart();
  const update = useUpdatePart();

  // The chosen category is mirrored here, not read out of the form, because the schema it
  // fetches decides both the fields and the rules the form is built with.
  const [categoryId, setCategoryId] = useState(part?.category_id ?? "");
  const schema = useCategorySchema(categoryId || null);
  const attributes = schema.data?.attributes ?? [];
  // Rebuilt whenever the fields change, which is what makes the rules follow the category.
  const resolver = useMemo(() => partResolver(attributes, t), [attributes, t]);
  const form = useForm<PartFormValues>({ defaultValues: startingValues(part), resolver });

  const saving = define.isPending || update.isPending;
  const rootError = form.formState.errors.root?.message;
  // What was already flagged on this part, so the fields to fix are marked while it is being
  // edited (requirement 7.6). Saving has to make the whole map valid, which clears them all.
  const problems = problemsByKey(part?.problems ?? [], t);

  function save(values: PartFormValues) {
    const body = requestFrom(values, attributes);
    const failed = (error: unknown) => showRefusal(error, form, attributes, t);
    if (part) update.mutate({ partId: part.id, body }, { onSuccess: onSaved, onError: failed });
    else define.mutate(body, { onSuccess: onSaved, onError: failed });
  }

  return (
    <form
      // Kept off the browser's own validation: the messages here are translated and
      // rendered where the field is, which native bubbles can't do.
      noValidate
      onSubmit={(event) => void form.handleSubmit(save)(event)}
      className="grid max-w-2xl gap-4"
    >
      <CategoryChoice form={form} categories={categories.data ?? []} onPicked={setCategoryId} />
      <DetailField name="name" label={t("catalog.form.name")} form={form} />
      <DetailField name="manufacturer" label={t("catalog.form.manufacturer")} form={form} />
      <DetailField name="mpn" label={t("catalog.form.mpn")} form={form} />
      <DetailField name="package" label={t("catalog.form.package")} form={form} />

      <fieldset className="grid gap-3 rounded-lg border border-border bg-surface p-4">
        <legend className="px-1 text-sm font-semibold">{t("catalog.form.fields")}</legend>
        {categoryId === "" && <p className="text-sm text-muted">{t("catalog.form.pickFirst")}</p>}
        {schema.isPending && categoryId !== "" && (
          <p className="text-sm text-muted">{t("catalog.form.loadingFields")}</p>
        )}
        {schema.isError && (
          <p role="alert" className="text-sm text-crit">
            {t("catalog.form.fieldsError")}
          </p>
        )}
        {schema.data && attributes.length === 0 && (
          <p className="text-sm text-muted">{t("catalog.form.noFields")}</p>
        )}
        {attributes.map((attribute) => (
          <AttributeField
            key={attribute.id}
            attribute={attribute}
            form={form}
            problem={problems.get(attribute.key)}
          />
        ))}
      </fieldset>

      {rootError && (
        <p role="alert" className="rounded-md border border-crit px-3 py-2 text-sm text-crit">
          {rootError}
        </p>
      )}

      <div className="flex flex-wrap gap-3">
        <button
          type="submit"
          disabled={saving}
          className="rounded-md bg-primary px-4 py-2 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {saving ? t("catalog.form.saving") : t("catalog.form.save")}
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
          >
            {t("catalog.form.cancel")}
          </button>
        )}
      </div>
    </form>
  );
}

/** The page behind `/parts/new`: the form, then straight to the part it created. */
export function NewPartPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <section className="grid gap-4">
      <h1 className="font-display text-3xl font-semibold tracking-tight">
        {t("catalog.form.newTitle")}
      </h1>
      <PartForm
        onSaved={(part) => void navigate({ to: "/parts/$partId", params: { partId: part.id } })}
      />
    </section>
  );
}

function startingValues(part: PartDetails | undefined): PartFormValues {
  return {
    categoryId: part?.category_id ?? "",
    name: part?.name ?? "",
    manufacturer: part?.manufacturer ?? "",
    mpn: part?.mpn ?? "",
    package: part?.package ?? "",
    attributes: storedValues(part?.attributes ?? {}),
  };
}

function requestFrom(values: PartFormValues, attributes: SchemaAttribute[]): NewPart {
  return {
    category_id: values.categoryId,
    name: values.name.trim(),
    manufacturer: filled(values.manufacturer),
    mpn: filled(values.mpn),
    package: filled(values.package),
    attributes: sentAttributes(values.attributes, attributes),
  };
}

/**
 * A refusal, shown where it belongs (requirement 7.5). A 422 names the attribute at the
 * start of its message, a 409 on a part is always the part number already being taken, and
 * anything else is the form's problem rather than one field's.
 */
function showRefusal(
  error: unknown,
  form: UseFormReturn<PartFormValues>,
  attributes: SchemaAttribute[],
  t: TFunction,
): void {
  const refusal = error instanceof CatalogRefusal ? error : null;
  const detail = refusal?.detail ?? "";
  const named = attributeNamedIn(detail, attributes);
  if (named) form.setError(`attributes.${named}`, { type: "server", message: detail });
  else if (refusal?.status === 409) form.setError("mpn", { type: "server", message: detail });
  else form.setError("root", { type: "server", message: detail || t("catalog.form.error.save") });
}

function attributeNamedIn(detail: string, attributes: SchemaAttribute[]): string | null {
  // "resistance takes a number, not text" and "'depth' is not an attribute of this category".
  const message = detail.trim().replace(/^['"]/, "");
  return attributes.find((attribute) => message.startsWith(attribute.key))?.key ?? null;
}
