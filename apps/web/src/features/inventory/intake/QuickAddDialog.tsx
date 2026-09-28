import { Link } from "@tanstack/react-router";
import type {
  CategoryNode,
  CellProblem,
  PartDetails,
  QuickAddRequest,
  QuickAddResponse,
  QuickStockBody,
  SchemaAttribute,
} from "@wiredex/api-client";
import type { TFunction } from "i18next";
import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { type FieldPath, type UseFormReturn, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { AttributeField } from "../../catalog/AttributeField";
import { useCategories, useCategorySchema } from "../../catalog/catalog";
import {
  CategoryChoice,
  DetailField,
  filled,
  type PartFormValues,
  partResolver,
  sentAttributes,
} from "../../catalog/partFields";
import { locationPath, useLocations } from "../inventory";
import { LocationPicker } from "../LocationPicker";
import { control, dialogPrimary, StockDialog } from "../StockDialog";
import { IntakeRefusal, type TakenPart, useQuickAddPart } from "./intake";
import { problemText } from "./problems";

/** What another part of the app can open quick-add with (requirement 2.7). */
export type QuickAddOptions = {
  /** A part to start from: its category, name, manufacturer and package; never its number. */
  duplicateOf?: PartDetails;
  categoryId?: string;
  locationId?: string;
  /** The name to start with, such as the text the palette has already been typed into. */
  name?: string;
};

// A receipt's caps (design decision 10), which the API checks again: at most 100 units at
// once, or a million of a lot.
const MAX_UNITS = 100;
const MAX_LOT = 1_000_000;

/** The part fields in the order they are shown, which is the order focus looks through. */
const PART_FIELDS = ["categoryId", "name", "mpn", "manufacturer", "package"] as const;

/** What a form starts with: the options it was opened with, or what *Add another* keeps. */
type Start = {
  categoryId: string;
  name: string;
  manufacturer: string;
  package: string;
  locationId: string | null;
};

/** What was added, for the dialog to say once it is done. */
type Added = { response: QuickAddResponse; quantity: number | null; location: string | null };

type StockErrors = { location?: string; quantity?: string };

type Props = { options: QuickAddOptions; onClose: () => void };

/**
 * Quick-add: a part and its first stock from one short form (requirements 1, 2).
 *
 * The part half is the part form's own fields and rules; the stock half is one location and
 * one quantity, received as a lot or, for a category tracked individually, as that many units
 * (design decision 11). Enter submits from any field. What the API refuses lands on the field
 * it names, and a part number already in the catalog links to the part that holds it. Once
 * added, the dialog says what it added and offers *Add another*, which keeps what a bag of
 * parts has in common (decision 14), or *Open the part*.
 */
export function QuickAddDialog({ options, onClose }: Props) {
  const { t } = useTranslation();
  const categories = useCategories();
  const [start, setStart] = useState(() => startFrom(options));
  // Each form is a fresh one, so *Add another* starts over from what it keeps.
  const [round, setRound] = useState(0);
  const [added, setAdded] = useState<Added | null>(null);

  function another() {
    setAdded(null);
    setRound((current) => current + 1);
  }

  return (
    <StockDialog title={t("inventory.quickAdd.title")} onClose={onClose} wide>
      {/* Always there, so what was added is announced when it arrives (requirement 2.5). */}
      <div role="status" className={added ? "grid gap-2" : "sr-only"}>
        {added && <AddedMessage added={added} />}
      </div>

      {added && <DonePanel partId={added.response.part_id} onAnother={another} onClose={onClose} />}
      {!added && categories.isPending && (
        <p className="text-muted">{t("inventory.quickAdd.loading")}</p>
      )}
      {!added && categories.isError && (
        <p role="alert" className="text-crit">
          {t("inventory.quickAdd.categoriesError")}
        </p>
      )}
      {!added && categories.data && (
        <QuickAddForm
          key={round}
          categories={categories.data}
          start={start}
          onCancel={onClose}
          onAdded={(result, kept) => {
            setStart(kept);
            setAdded(result);
          }}
        />
      )}
    </StockDialog>
  );
}

type FormProps = {
  categories: CategoryNode[];
  start: Start;
  onCancel: () => void;
  onAdded: (added: Added, kept: Start) => void;
};

function QuickAddForm({ categories, start, onCancel, onAdded }: FormProps) {
  const { t } = useTranslation();
  const quickAdd = useQuickAddPart();
  const locations = useLocations();
  const stockHintId = useId();
  const locationErrorId = useId();
  const quantityId = useId();
  const quantityHintId = useId();
  const quantityErrorId = useId();
  const locationRef = useRef<HTMLInputElement>(null);
  const quantityRef = useRef<HTMLInputElement>(null);

  // A category that is gone since the options were given is no category at all.
  const known = categories.some((category) => category.id === start.categoryId);
  const [categoryId, setCategoryId] = useState(known ? start.categoryId : "");
  const schema = useCategorySchema(categoryId || null);
  const attributes = schema.data?.attributes ?? [];
  const resolver = useMemo(() => partResolver(attributes, t), [attributes, t]);
  const form = useForm<PartFormValues>({
    defaultValues: {
      categoryId: known ? start.categoryId : "",
      name: start.name,
      manufacturer: start.manufacturer,
      mpn: "",
      package: start.package,
      attributes: {},
    },
    resolver,
  });

  const [locationId, setLocationId] = useState(start.locationId);
  const [quantity, setQuantity] = useState("");
  const [stockErrors, setStockErrors] = useState<StockErrors>({});
  const [taken, setTaken] = useState<TakenPart | null>(null);
  const [formProblems, setFormProblems] = useState<string[]>([]);

  // The count follows the category's resolved flag, as the API reads it (requirement 1.3).
  const tracked =
    categories.find((category) => category.id === categoryId)?.tracked_individually_resolved ??
    false;
  const max = tracked ? MAX_UNITS : MAX_LOT;

  // The first empty field takes focus, so an opened dialog is typed into at once, and *Add
  // another*, which keeps the category, starts at the name (requirements 2.3, 2.6).
  useEffect(() => {
    const values = form.getValues();
    form.setFocus(PART_FIELDS.find((field) => values[field].trim() === "") ?? "name");
  }, [form]);

  function submit(event: FormEvent<HTMLFormElement>) {
    if (quickAdd.isPending) {
      event.preventDefault();
      return;
    }
    const checked = checkStock(locationId, quantity, max, t);
    setStockErrors(checked.errors);
    setTaken(null);
    setFormProblems([]);
    void form.handleSubmit((values) => {
      // The part's own fields were fine; the stock half isn't, so that is where focus goes.
      if (checked.errors.location) locationRef.current?.focus();
      else if (checked.errors.quantity) quantityRef.current?.focus();
      else send(values, checked.stock);
    })(event);
  }

  function send(values: PartFormValues, stock: QuickStockBody | null) {
    const body: QuickAddRequest = {
      part: {
        category_id: values.categoryId,
        name: filled(values.name),
        manufacturer: filled(values.manufacturer),
        mpn: filled(values.mpn),
        package: filled(values.package),
        attributes: sentAttributes(values.attributes, attributes),
      },
      ...(stock ? { stock } : {}),
    };
    const picked = (locations.data ?? []).find((location) => location.id === stock?.location_id);
    quickAdd.mutate(body, {
      onSuccess: (response) =>
        onAdded(
          {
            response,
            quantity: stock?.quantity ?? null,
            location: picked ? locationPath(picked, locations.data ?? []) : null,
          },
          {
            categoryId: values.categoryId,
            name: "",
            manufacturer: values.manufacturer,
            package: values.package,
            locationId,
          },
        ),
      onError: showRefusal,
    });
  }

  /**
   * A refusal, on the fields it names (requirements 1.5, 1.6). Every problem of a 422 lands on
   * its field, several on one field side by side, and focus goes to the first of them; a 409
   * marks the part number and links to the part that holds it; anything else is the form's.
   */
  function showRefusal(error: unknown) {
    const refusal = error instanceof IntakeRefusal ? error : null;
    if (refusal?.taken) {
      setTaken(refusal.taken);
      const message = t("inventory.quickAdd.taken", { name: refusal.taken.name });
      form.setError("mpn", { type: "server", message }, { shouldFocus: true });
      return;
    }
    if (!refusal || refusal.problems.length === 0) {
      setFormProblems([refusal?.detail || t("inventory.quickAdd.error.save")]);
      return;
    }
    const placed = placeProblems(refusal.problems, attributes, t);
    for (const [field, message] of placed.part) form.setError(field, { type: "server", message });
    setStockErrors(placed.stock);
    setFormProblems(placed.form);
    focusFirst(placed, attributes, form, { location: locationRef, quantity: quantityRef });
  }

  function onKeyDown(event: KeyboardEvent<HTMLFormElement>) {
    // Enter submits from any field, a select or a switch too (requirement 2.3), but not from
    // a button, which Enter presses, nor while the location list is open, which it picks from.
    if (event.key !== "Enter" || event.nativeEvent.defaultPrevented) return;
    if (event.nativeEvent.isComposing) return;
    const target = event.target;
    if (target instanceof HTMLButtonElement || target instanceof HTMLAnchorElement) return;
    event.preventDefault();
    event.currentTarget.requestSubmit();
  }

  const quantityDescribedBy =
    [tracked ? quantityHintId : null, stockErrors.quantity ? quantityErrorId : null]
      .filter(Boolean)
      .join(" ") || undefined;

  return (
    <form noValidate onSubmit={submit} onKeyDown={onKeyDown} className="grid gap-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <CategoryChoice form={form} categories={categories} onPicked={setCategoryId} />
        </div>
        <div className="sm:col-span-2">
          <DetailField name="name" label={t("catalog.form.name")} form={form} />
        </div>
        <DetailField name="mpn" label={t("catalog.form.mpn")} form={form} />
        <DetailField name="manufacturer" label={t("catalog.form.manufacturer")} form={form} />
        <DetailField name="package" label={t("catalog.form.package")} form={form} />
      </div>

      {categoryId !== "" && <CategoryFields form={form} attributes={attributes} schema={schema} />}

      <fieldset
        aria-describedby={stockHintId}
        className="grid gap-3 rounded-lg border border-border p-4 sm:grid-cols-2"
      >
        <legend className="px-1 text-sm font-semibold">{t("inventory.quickAdd.stock")}</legend>
        <p id={stockHintId} className="text-sm text-muted sm:col-span-2">
          {t("inventory.quickAdd.stockHint")}
        </p>
        <div className="grid content-start gap-1">
          <LocationPicker
            ref={locationRef}
            label={t("inventory.quickAdd.location")}
            value={locationId}
            onChange={(picked) => {
              setLocationId(picked);
              setStockErrors(({ quantity }) => (quantity ? { quantity } : {}));
            }}
            {...(stockErrors.location ? { describedBy: locationErrorId, invalid: true } : {})}
          />
          {stockErrors.location && (
            <p id={locationErrorId} className="text-sm text-crit">
              {stockErrors.location}
            </p>
          )}
        </div>
        <div className="grid content-start gap-1">
          <label htmlFor={quantityId} className="text-sm font-medium">
            {tracked ? t("inventory.quickAdd.units") : t("inventory.quickAdd.quantity")}
          </label>
          <input
            ref={quantityRef}
            id={quantityId}
            type="number"
            inputMode="numeric"
            min={1}
            max={max}
            step={1}
            value={quantity}
            onChange={(event) => {
              setQuantity(event.target.value);
              setStockErrors(({ location }) => (location ? { location } : {}));
            }}
            aria-invalid={stockErrors.quantity ? true : undefined}
            aria-describedby={quantityDescribedBy}
            className={control}
          />
          {tracked && (
            <p id={quantityHintId} className="text-sm text-muted">
              {t("inventory.quickAdd.unitsHint")}
            </p>
          )}
          {stockErrors.quantity && (
            <p id={quantityErrorId} className="text-sm text-crit">
              {stockErrors.quantity}
            </p>
          )}
        </div>
      </fieldset>

      {taken && (
        <p className="text-sm">
          <Link
            to="/parts/$partId"
            params={{ partId: taken.partId }}
            onClick={onCancel}
            className="font-semibold text-primary underline"
          >
            {t("inventory.quickAdd.openTaken", { name: taken.name })}
          </Link>
        </p>
      )}
      {formProblems.length > 0 && (
        <div role="alert" className="grid gap-1 rounded-md border border-crit px-3 py-2 text-sm">
          {formProblems.map((problem) => (
            <p key={problem} className="text-crit">
              {problem}
            </p>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={quickAdd.isPending} className={dialogPrimary}>
          {quickAdd.isPending ? t("inventory.quickAdd.adding") : t("inventory.quickAdd.submit")}
        </button>
        <button type="button" onClick={onCancel} className={control}>
          {t("inventory.quickAdd.cancel")}
        </button>
      </div>
    </form>
  );
}

type FieldsProps = {
  form: UseFormReturn<PartFormValues>;
  attributes: SchemaAttribute[];
  schema: ReturnType<typeof useCategorySchema>;
};

/** The chosen category's own fields, as the part form draws them (requirement 1.1). */
function CategoryFields({ form, attributes, schema }: FieldsProps) {
  const { t } = useTranslation();
  if (schema.isPending) {
    return <p className="text-sm text-muted">{t("catalog.form.loadingFields")}</p>;
  }
  if (schema.isError) {
    return (
      <p role="alert" className="text-sm text-crit">
        {t("catalog.form.fieldsError")}
      </p>
    );
  }
  // Nothing to fill in is nothing to show: the stock follows straight on.
  if (attributes.length === 0) return null;
  return (
    <fieldset className="grid gap-3 rounded-lg border border-border p-4 sm:grid-cols-2">
      <legend className="px-1 text-sm font-semibold">{t("catalog.form.fields")}</legend>
      {attributes.map((attribute) => (
        <AttributeField key={attribute.id} attribute={attribute} form={form} />
      ))}
    </fieldset>
  );
}

function AddedMessage({ added }: { added: Added }) {
  const { t } = useTranslation();
  const { response, quantity, location } = added;
  const at = location ?? "";
  let message = t("inventory.quickAdd.added", { name: response.name });
  if (response.units.length > 0) {
    message = t("inventory.quickAdd.addedUnits", { name: response.name, location: at });
  } else if (quantity !== null) {
    message = t("inventory.quickAdd.addedLot", { name: response.name, quantity, location: at });
  }

  return (
    <>
      <p className="font-semibold text-ok">{message}</p>
      {response.units.length > 0 && (
        <ul aria-label={t("inventory.quickAdd.codes")} className="grid gap-1 font-mono text-sm">
          {response.units.map((unit) => (
            <li key={unit.id}>{unit.code}</li>
          ))}
        </ul>
      )}
    </>
  );
}

type DoneProps = { partId: string; onAnother: () => void; onClose: () => void };

/** What comes after an addition: *Add another* focused, so Enter starts the next part. */
function DonePanel({ partId, onAnother, onClose }: DoneProps) {
  const { t } = useTranslation();
  const anotherRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    anotherRef.current?.focus();
  }, []);

  return (
    <div className="flex flex-wrap gap-2">
      <button ref={anotherRef} type="button" onClick={onAnother} className={dialogPrimary}>
        {t("inventory.quickAdd.another")}
      </button>
      <Link
        to="/parts/$partId"
        params={{ partId }}
        onClick={onClose}
        className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
      >
        {t("inventory.quickAdd.openPart")}
      </Link>
      <button type="button" onClick={onClose} className={control}>
        {t("inventory.quickAdd.close")}
      </button>
    </div>
  );
}

function startFrom(options: QuickAddOptions): Start {
  const source = options.duplicateOf;
  return {
    categoryId: options.categoryId ?? source?.category_id ?? "",
    name: options.name ?? source?.name ?? "",
    manufacturer: source?.manufacturer ?? "",
    package: source?.package ?? "",
    locationId: options.locationId ?? null,
  };
}

/**
 * The stock half as the API takes it, or why it can't be sent. Both halves or neither
 * (requirement 1.7), and a whole number within the receipt's cap (1.8), so a request the API
 * would refuse for its shape alone never goes out.
 */
function checkStock(
  locationId: string | null,
  quantity: string,
  max: number,
  t: TFunction,
): { stock: QuickStockBody | null; errors: StockErrors } {
  const typed = quantity.trim();
  if (locationId === null && typed === "") return { stock: null, errors: {} };
  const errors: StockErrors = {};
  if (locationId === null) errors.location = t("inventory.intake.problem.location_needed");
  const amount = Number(typed);
  if (typed === "") errors.quantity = t("inventory.intake.problem.quantity_needed");
  else if (!Number.isInteger(amount) || amount < 1 || amount > max) {
    errors.quantity = t("inventory.quickAdd.error.quantity", { max });
  }
  if (locationId === null || errors.quantity) return { stock: null, errors };
  return { stock: { location_id: locationId, quantity: amount }, errors };
}

type Placed = {
  part: Map<FieldPath<PartFormValues>, string>;
  stock: StockErrors;
  form: string[];
};

/**
 * Each problem on the field its column names (design, "How features compose"): a detail by
 * its own name, `category` on the category, an attribute key on that attribute's field, and
 * `location` and `quantity` on the stock. Anything else, such as a key the category doesn't
 * define, is the form's own.
 */
function placeProblems(
  problems: readonly CellProblem[],
  attributes: SchemaAttribute[],
  t: TFunction,
): Placed {
  const part = new Map<FieldPath<PartFormValues>, string>();
  const stock: StockErrors = {};
  const form: string[] = [];
  const add = (current: string | undefined, text: string) =>
    current ? `${current} ${text}` : text;

  for (const problem of problems) {
    const text = problemText(problem, t);
    const column = problem.column;
    if (column === "location" || column === "quantity") {
      stock[column] = add(stock[column], text);
      continue;
    }
    const field = fieldOf(column, attributes);
    if (field) part.set(field, add(part.get(field), text));
    else form.push(text);
  }
  return { part, stock, form };
}

function fieldOf(
  column: string | null,
  attributes: SchemaAttribute[],
): FieldPath<PartFormValues> | null {
  if (column === "category") return "categoryId";
  if (column === "name" || column === "manufacturer" || column === "mpn") return column;
  if (column === "package") return column;
  if (column !== null && attributes.some((attribute) => attribute.key === column)) {
    return `attributes.${column}`;
  }
  return null;
}

type StockRefs = {
  location: { current: HTMLInputElement | null };
  quantity: { current: HTMLInputElement | null };
};

/** Focus on the first field a refusal marked, in the order the form shows them. */
function focusFirst(
  placed: Placed,
  attributes: SchemaAttribute[],
  form: UseFormReturn<PartFormValues>,
  refs: StockRefs,
): void {
  const partOrder: FieldPath<PartFormValues>[] = [
    ...PART_FIELDS,
    ...attributes.map((attribute): FieldPath<PartFormValues> => `attributes.${attribute.key}`),
  ];
  const first = partOrder.find((field) => placed.part.has(field));
  if (first) form.setFocus(first);
  else if (placed.stock.location) refs.location.current?.focus();
  else if (placed.stock.quantity) refs.quantity.current?.focus();
}
