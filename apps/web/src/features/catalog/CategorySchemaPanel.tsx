import type { AttributeKind, CategoryNode, SchemaAttribute } from "@wiredex/api-client";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  categoryName,
  refusalMessage,
  useCategories,
  useCategorySchema,
  useDefineAttribute,
  useEditAttribute,
  useRemoveAttribute,
} from "./catalog";

const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";
const action = "rounded-md border border-border-strong px-3 py-1 text-sm hover:bg-surface-2";
const KINDS: AttributeKind[] = ["number", "enum", "text", "bool"];

/**
 * The fields a category's parts have: its own, which can be changed here, and the ones it
 * inherits, which belong to the category above and are shown marked (requirements 2.7, 7.7).
 */
export function CategorySchemaPanel({ category }: { category: CategoryNode }) {
  const { t } = useTranslation();
  const schema = useCategorySchema(category.id);
  const categories = useCategories();
  const remove = useRemoveAttribute();
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const attributes = schema.data?.attributes ?? [];

  return (
    <section
      aria-label={t("catalog.schema.title", { name: category.name })}
      className="grid gap-3 rounded-lg border border-border bg-surface p-4"
    >
      <h2 className="font-display text-xl font-semibold">{t("catalog.schema.heading")}</h2>

      {schema.isPending && <p className="text-muted">{t("catalog.form.loadingFields")}</p>}
      {schema.isError && (
        <p role="alert" className="text-crit">
          {t("catalog.form.fieldsError")}
        </p>
      )}
      {schema.data && attributes.length === 0 && (
        <p className="text-muted">{t("catalog.schema.none")}</p>
      )}

      {attributes.length > 0 && (
        <ul className="grid gap-2">
          {attributes.map((attribute) => (
            <li key={attribute.id} className="grid gap-2 border-b border-border pb-2">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="font-medium">{attribute.label}</span>
                <span className="font-mono text-sm text-muted">{attribute.key}</span>
                <span className="text-sm text-muted">
                  {t(`catalog.schema.kinds.${attribute.kind}`)}
                  {attribute.unit ? ` · ${attribute.unit}` : ""}
                </span>
                {attribute.required && (
                  <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-primary">
                    {t("catalog.schema.required")}
                  </span>
                )}
                {attribute.inherited ? (
                  <span className="text-sm text-muted">
                    {t("catalog.schema.inherited", {
                      name:
                        categoryName(categories.data, attribute.category_id) ??
                        t("catalog.schema.anotherCategory"),
                    })}
                  </span>
                ) : (
                  <span className="ml-auto flex gap-2">
                    <button
                      type="button"
                      className={action}
                      onClick={() => setEditing(editing === attribute.id ? null : attribute.id)}
                      aria-label={t("catalog.schema.editField", { name: attribute.label })}
                    >
                      {t("catalog.schema.edit")}
                    </button>
                    <button
                      type="button"
                      className={action}
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(attribute.id)}
                      aria-label={t("catalog.schema.removeField", { name: attribute.label })}
                    >
                      {t("catalog.schema.remove")}
                    </button>
                  </span>
                )}
              </div>
              {editing === attribute.id && (
                <AttributeForm
                  categoryId={category.id}
                  attribute={attribute}
                  onDone={() => setEditing(null)}
                />
              )}
            </li>
          ))}
        </ul>
      )}

      {remove.isError && (
        <p role="alert" className="text-sm text-crit">
          {refusalMessage(remove.error) ?? t("catalog.schema.removeError")}
        </p>
      )}

      {adding ? (
        <AttributeForm
          categoryId={category.id}
          // A new field goes after the ones this category already declares.
          position={attributes.filter((attribute) => !attribute.inherited).length}
          onDone={() => setAdding(false)}
        />
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="justify-self-start rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2"
        >
          {t("catalog.schema.add")}
        </button>
      )}
    </section>
  );
}

type FormProps = {
  categoryId: string;
  /** Set when an existing field is being changed: its key and kind are then fixed. */
  attribute?: SchemaAttribute;
  /** Where a new field lands in the order. An existing one keeps the place it has. */
  position?: number;
  onDone: () => void;
};

function AttributeForm({ categoryId, attribute, position = 0, onDone }: FormProps) {
  const { t } = useTranslation();
  const ids = { key: useId(), label: useId(), kind: useId(), unit: useId(), options: useId() };
  const define = useDefineAttribute();
  const edit = useEditAttribute();
  const [kind, setKind] = useState<AttributeKind>(attribute?.kind ?? "number");

  const saving = define.isPending || edit.isPending;
  const failure = define.error ?? edit.error;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const label = text(form.get("label"));
    const required = form.get("required") === "on";
    const options = lines(form.get("options"));
    if (label === "") return;

    if (attribute) {
      // Neither the key nor the kind travels: changing either is a different field (2.9).
      edit.mutate(
        { attributeId: attribute.id, body: { label, required, options } },
        { onSuccess: onDone },
      );
      return;
    }
    const key = text(form.get("key"));
    if (key === "") return;
    define.mutate(
      {
        categoryId,
        body: {
          key,
          label,
          kind,
          unit: text(form.get("unit")) || null,
          required,
          options,
          position,
        },
      },
      { onSuccess: onDone },
    );
  }

  return (
    <form onSubmit={submit} className="grid gap-2 rounded-md bg-surface-2 p-3">
      <div className="grid gap-1">
        <label htmlFor={ids.key} className="text-sm font-medium">
          {t("catalog.schema.key")}
        </label>
        <input
          id={ids.key}
          name="key"
          type="text"
          defaultValue={attribute?.key ?? ""}
          // A key can't move to another field's values, so an existing one is read-only.
          readOnly={attribute !== undefined}
          className={control}
        />
      </div>
      <div className="grid gap-1">
        <label htmlFor={ids.label} className="text-sm font-medium">
          {t("catalog.schema.label")}
        </label>
        <input
          id={ids.label}
          name="label"
          type="text"
          defaultValue={attribute?.label ?? ""}
          className={control}
        />
      </div>
      <div className="grid gap-1">
        <label htmlFor={ids.kind} className="text-sm font-medium">
          {t("catalog.schema.kind")}
        </label>
        <select
          id={ids.kind}
          name="kind"
          value={kind}
          disabled={attribute !== undefined}
          onChange={(event) => setKind(event.target.value as AttributeKind)}
          className={control}
        >
          {KINDS.map((option) => (
            <option key={option} value={option}>
              {t(`catalog.schema.kinds.${option}`)}
            </option>
          ))}
        </select>
      </div>
      {kind === "number" && (
        <div className="grid gap-1">
          <label htmlFor={ids.unit} className="text-sm font-medium">
            {t("catalog.schema.unit")}
          </label>
          <input
            id={ids.unit}
            name="unit"
            type="text"
            defaultValue={attribute?.unit ?? ""}
            readOnly={attribute !== undefined}
            className={control}
          />
        </div>
      )}
      {kind === "enum" && (
        <div className="grid gap-1">
          <label htmlFor={ids.options} className="text-sm font-medium">
            {t("catalog.schema.options")}
          </label>
          <textarea
            id={ids.options}
            name="options"
            rows={3}
            defaultValue={(attribute?.options ?? []).join("\n")}
            className={control}
          />
          <p className="text-sm text-muted">{t("catalog.schema.optionsHint")}</p>
        </div>
      )}
      <label className="flex items-center gap-2 text-sm font-medium">
        <input
          name="required"
          type="checkbox"
          defaultChecked={attribute?.required ?? false}
          className="size-4 accent-primary"
        />
        {t("catalog.schema.required")}
      </label>
      {failure && (
        <p role="alert" className="text-sm text-crit">
          {refusalMessage(failure) ?? t("catalog.schema.saveError")}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {saving ? t("catalog.schema.saving") : t("catalog.schema.save")}
        </button>
        <button type="button" onClick={onDone} className={action}>
          {t("catalog.schema.cancel")}
        </button>
      </div>
    </form>
  );
}

function text(value: FormDataEntryValue | null): string {
  return typeof value === "string" ? value.trim() : "";
}

/** One option per line, which is how a list is typed without inventing a widget for it. */
function lines(value: FormDataEntryValue | null): string[] {
  return text(value)
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}
