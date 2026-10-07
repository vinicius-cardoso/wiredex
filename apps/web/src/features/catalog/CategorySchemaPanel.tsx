import type { AttributeKind, CategoryNode, SchemaAttribute } from "@wiredex/api-client";
import { type FormEvent, useId, useRef, useState } from "react";
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
const action =
  "rounded-md border border-border-strong px-2.5 py-1 text-sm whitespace-nowrap hover:bg-surface-2";
const KINDS: AttributeKind[] = ["number", "enum", "text", "bool"];

/**
 * The fields a category's parts have, as a table: its own, which can be changed here, and the
 * ones it inherits, which belong to the category above and are shown marked (requirements 2.7,
 * 7.7).
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
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-lg font-semibold">{t("catalog.schema.heading")}</h2>
        {!adding && (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="inline-flex h-8 items-center rounded-md border border-border-strong px-3 text-sm hover:bg-surface-2"
          >
            {t("catalog.schema.add")}
          </button>
        )}
      </div>

      {schema.isPending && <p className="text-sm text-muted">{t("catalog.form.loadingFields")}</p>}
      {schema.isError && (
        <p role="alert" className="text-sm text-crit">
          {t("catalog.form.fieldsError")}
        </p>
      )}
      {schema.data && attributes.length === 0 && (
        <p className="text-sm text-muted">{t("catalog.schema.none")}</p>
      )}

      {attributes.length > 0 && (
        // A long label or option list scrolls the table inside its own box, never the page.
        // Positioned, so the screen-reader-only headers, placed absolutely, scroll and clip with
        // this box; otherwise the actions header escapes it and widens the page on a phone.
        <div className="relative overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">{t("catalog.schema.heading")}</caption>
            <thead className="border-b border-border text-muted">
              <tr>
                <th scope="col" className={headCell}>
                  {t("catalog.schema.label")}
                </th>
                <th scope="col" className={headCell}>
                  {t("catalog.schema.key")}
                </th>
                <th scope="col" className={headCell}>
                  {t("catalog.schema.kind")}
                </th>
                <th scope="col" className={headCell}>
                  {t("catalog.schema.required")}
                </th>
                <th scope="col" className={headCell}>
                  <span className="sr-only">{t("catalog.schema.actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {attributes.map((attribute) => (
                <FieldRow
                  key={attribute.id}
                  attribute={attribute}
                  categoryId={category.id}
                  inheritedFrom={
                    attribute.inherited
                      ? (categoryName(categories.data, attribute.category_id) ??
                        t("catalog.schema.anotherCategory"))
                      : null
                  }
                  editing={editing === attribute.id}
                  onEdit={() => setEditing(editing === attribute.id ? null : attribute.id)}
                  onEdited={() => setEditing(null)}
                  onRemove={() => remove.mutate(attribute.id)}
                  removing={remove.isPending}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {remove.isError && (
        <p role="alert" className="text-sm text-crit">
          {refusalMessage(remove.error) ?? t("catalog.schema.removeError")}
        </p>
      )}

      {adding && (
        <AttributeForm
          categoryId={category.id}
          // A new field goes after the ones this category already declares.
          position={attributes.filter((attribute) => !attribute.inherited).length}
          onDone={() => setAdding(false)}
        />
      )}
    </section>
  );
}

const headCell = "px-2 py-1.5 font-medium whitespace-nowrap";
const cell = "px-2 py-1.5 align-top";

type FieldRowProps = {
  attribute: SchemaAttribute;
  categoryId: string;
  /** The category above it belongs to, for an inherited field; null for the category's own. */
  inheritedFrom: string | null;
  editing: boolean;
  onEdit: () => void;
  onEdited: () => void;
  onRemove: () => void;
  removing: boolean;
};

/**
 * One field: its label, key, kind with its unit, whether it is required, and where it comes
 * from. Only the category's own fields are changed here; an inherited one belongs to the
 * category above (requirements 2.7, 7.7). Being edited, its form takes the row under it.
 */
function FieldRow({
  attribute,
  categoryId,
  inheritedFrom,
  editing,
  onEdit,
  onEdited,
  onRemove,
  removing,
}: FieldRowProps) {
  const { t } = useTranslation();

  return (
    <>
      <tr className="border-b border-border last:border-b-0">
        <th scope="row" className={`${cell} font-medium`}>
          {attribute.label}
        </th>
        <td className={`${cell} font-mono text-xs text-muted`}>{attribute.key}</td>
        <td className={`${cell} text-muted`}>
          {t(`catalog.schema.kinds.${attribute.kind}`)}
          {attribute.unit ? ` · ${attribute.unit}` : ""}
        </td>
        <td className={cell}>
          {attribute.required && (
            <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-primary">
              {t("catalog.schema.required")}
            </span>
          )}
        </td>
        <td className={`${cell} text-right`}>
          {inheritedFrom !== null ? (
            <span className="text-muted">
              {t("catalog.schema.inherited", { name: inheritedFrom })}
            </span>
          ) : (
            <span className="inline-flex gap-2">
              <button
                type="button"
                className={action}
                onClick={onEdit}
                aria-label={t("catalog.schema.editField", { name: attribute.label })}
              >
                {t("catalog.schema.edit")}
              </button>
              <button
                type="button"
                className={action}
                disabled={removing}
                onClick={onRemove}
                aria-label={t("catalog.schema.removeField", { name: attribute.label })}
              >
                {t("catalog.schema.remove")}
              </button>
            </span>
          )}
        </td>
      </tr>
      {editing && (
        <tr>
          <td colSpan={5} className="pb-3">
            <AttributeForm categoryId={categoryId} attribute={attribute} onDone={onEdited} />
          </td>
        </tr>
      )}
    </>
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
  // The field left blank that a field can't be saved without, said under it.
  const [missing, setMissing] = useState<"key" | "label" | null>(null);
  const keyRef = useRef<HTMLInputElement>(null);
  const labelRef = useRef<HTMLInputElement>(null);
  const missingId = useId();

  const saving = define.isPending || edit.isPending;
  const failure = define.error ?? edit.error;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const label = text(form.get("label"));
    const required = form.get("required") === "on";
    const options = lines(form.get("options"));
    const key = text(form.get("key"));
    // Neither can be blank; the first one that is says so and takes the focus, rather than
    // Save doing nothing.
    const blank = !attribute && key === "" ? "key" : label === "" ? "label" : null;
    setMissing(blank);
    if (blank) {
      (blank === "key" ? keyRef : labelRef).current?.focus();
      return;
    }

    if (attribute) {
      // Neither the key nor the kind travels: changing either is a different field (2.9).
      edit.mutate(
        { attributeId: attribute.id, body: { label, required, options } },
        { onSuccess: onDone },
      );
      return;
    }
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
    // Side by side where there is room, so the form stays a few lines tall.
    <form
      onSubmit={submit}
      className="grid items-start gap-2 rounded-md bg-surface-2 p-3 sm:grid-cols-2 xl:grid-cols-4"
    >
      <div className="grid gap-1">
        <label htmlFor={ids.key} className="text-sm font-medium">
          {t("catalog.schema.key")}
        </label>
        <input
          ref={keyRef}
          id={ids.key}
          name="key"
          type="text"
          aria-required="true"
          aria-invalid={missing === "key" || undefined}
          aria-describedby={missing === "key" ? missingId : undefined}
          onInput={() => setMissing(null)}
          defaultValue={attribute?.key ?? ""}
          // A key can't move to another field's values, so an existing one is read-only.
          readOnly={attribute !== undefined}
          className={control}
        />
        {missing === "key" && (
          <p id={missingId} role="alert" className="text-sm text-crit">
            {t("catalog.schema.missing")}
          </p>
        )}
      </div>
      <div className="grid gap-1">
        <label htmlFor={ids.label} className="text-sm font-medium">
          {t("catalog.schema.label")}
        </label>
        <input
          ref={labelRef}
          id={ids.label}
          name="label"
          type="text"
          aria-required="true"
          aria-invalid={missing === "label" || undefined}
          aria-describedby={missing === "label" ? missingId : undefined}
          onInput={() => setMissing(null)}
          defaultValue={attribute?.label ?? ""}
          className={control}
        />
        {missing === "label" && (
          <p id={missingId} role="alert" className="text-sm text-crit">
            {t("catalog.schema.missing")}
          </p>
        )}
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
      <label className="flex items-center gap-2 self-center text-sm font-medium">
        <input
          name="required"
          type="checkbox"
          defaultChecked={attribute?.required ?? false}
          className="size-4 accent-primary"
        />
        {t("catalog.schema.required")}
      </label>
      {failure && (
        <p role="alert" className="text-sm text-crit sm:col-span-full">
          {refusalMessage(failure) ?? t("catalog.schema.saveError")}
        </p>
      )}
      <div className="flex flex-wrap gap-2 sm:col-span-full">
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
