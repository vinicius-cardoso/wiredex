import { Link, useNavigate } from "@tanstack/react-router";
import type { AttributeValue, PartDetails, SchemaAttribute } from "@wiredex/api-client";
import type { TFunction } from "i18next";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { AttachmentsSection } from "../files/AttachmentsSection";
import { HistorySection } from "../history/HistorySection";
import { useQuickAdd } from "../inventory/intake/QuickAddProvider";
import { StockByPart } from "../inventory/StockByPart";
import { PinUsageSection } from "../projects/netlist/PinUsageSection";
import { CatalogRefusal, useCategorySchema, useDeletePart, usePart } from "./catalog";
import { PartForm } from "./PartForm";
import { PinoutEditor } from "./pinout/PinoutEditor";
import { PinoutSection } from "./pinout/PinoutSection";
import { problemsByKey } from "./review";

export function PartPage({ partId }: { partId: string }) {
  const { t } = useTranslation();
  const part = usePart(partId);
  const [editing, setEditing] = useState(false);

  return (
    <section className="grid max-w-3xl gap-4">
      <Link to="/parts" className="text-sm text-muted hover:text-primary">
        {t("catalog.part.back")}
      </Link>
      {part.isPending && <p className="text-muted">{t("catalog.part.loading")}</p>}
      {part.isError && (
        <p role="alert" className="text-crit">
          {t("catalog.part.error")}
        </p>
      )}
      {part.data && !editing && <PartDetail part={part.data} onEdit={() => setEditing(true)} />}
      {part.data && editing && (
        <>
          <h1 className="font-display text-3xl font-semibold tracking-tight">
            {t("catalog.form.editTitle")}
          </h1>
          <PartForm
            part={part.data}
            onSaved={() => setEditing(false)}
            onCancel={() => setEditing(false)}
          />
        </>
      )}
    </section>
  );
}

function PartDetail({ part, onEdit }: { part: PartDetails; onEdit: () => void }) {
  const { t } = useTranslation();
  const schema = useCategorySchema(part.category_id);
  // Duplicating is quick-add started from this part (design decision 13).
  const quickAdd = useQuickAdd();
  // The pins are their own table, so they are edited on their own, without the part's form.
  const [editingPinout, setEditingPinout] = useState(false);
  const attributes = schema.data?.attributes ?? [];
  const problems = problemsByKey(part.problems, t);
  // Values under keys nothing defines any more are still stored, so they are still shown
  // (design §2.5); the schema doesn't list them, so they are gathered here.
  const dropped = Object.keys(part.attributes).filter(
    (key) => !attributes.some((attribute) => attribute.key === key),
  );

  return (
    <>
      <h1 className="font-display text-3xl font-semibold tracking-tight">{part.name}</h1>
      {part.needs_review && <ReviewBanner problems={[...problems.values()]} />}
      <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-[auto_1fr]">
        <Entry label={t("catalog.part.category")} value={schema.data?.category.name ?? null} />
        <Entry label={t("catalog.part.manufacturer")} value={part.manufacturer} />
        <Entry label={t("catalog.part.mpn")} value={part.mpn} />
        <Entry label={t("catalog.part.package")} value={part.package} />
      </dl>

      <h2 className="font-display text-xl font-semibold">{t("catalog.part.fields")}</h2>
      {schema.isPending && <p className="text-muted">{t("catalog.form.loadingFields")}</p>}
      {attributes.length === 0 && schema.data && (
        <p className="text-muted">{t("catalog.part.noFields")}</p>
      )}
      {(attributes.length > 0 || dropped.length > 0) && (
        <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-[auto_1fr]">
          {attributes.map((attribute) => (
            <Entry
              key={attribute.id}
              label={attribute.label}
              value={shownValue(attribute, part.attributes[attribute.key], t)}
              problem={problems.get(attribute.key)}
            />
          ))}
          {dropped.map((key) => (
            <Entry
              key={key}
              label={t("catalog.review.droppedField", { key })}
              value={part.attributes[key]?.display ?? null}
              problem={problems.get(key)}
            />
          ))}
        </dl>
      )}

      {editingPinout ? (
        <PinoutEditor part={part} onClose={() => setEditingPinout(false)} />
      ) : (
        <PinoutSection part={part} onEdit={() => setEditingPinout(true)} />
      )}

      {/* What each pin is wired to across the bench (spec 12, requirement 10.5). */}
      <PinUsageSection partId={part.id} />

      {/* The part's own resolved flags (09's requirement 1.5), not its category schema's. */}
      <StockByPart
        partId={part.id}
        unitTracked={part.tracked_individually}
        notStocked={part.not_stocked}
      />

      <AttachmentsSection owner={{ kind: "part", id: part.id }} />
      <HistorySection kind="part" recordId={part.id} />

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={onEdit}
          className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
        >
          {t("catalog.part.edit")}
        </button>
        <button
          type="button"
          onClick={() => quickAdd.open({ duplicateOf: part })}
          className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
        >
          {t("catalog.part.duplicate")}
        </button>
        <DeleteButton part={part} />
      </div>
    </>
  );
}

type EntryProps = { label: string; value: string | null; problem?: string | undefined };

function Entry({ label, value, problem }: EntryProps) {
  return (
    <>
      <dt className="text-sm text-muted">{label}</dt>
      <dd className={problem ? "text-warn" : undefined}>
        {value ?? "—"}
        {problem && <span className="block text-sm text-warn">{problem}</span>}
      </dd>
    </>
  );
}

/** What no longer fits, listed where it can't be missed (requirements 5.2, 7.6). */
function ReviewBanner({ problems }: { problems: string[] }) {
  const { t } = useTranslation();

  return (
    <div role="alert" className="grid gap-2 rounded-lg border border-warn bg-surface-2 p-4">
      <p className="font-semibold text-warn">{t("catalog.review.title")}</p>
      <p className="text-sm">{t("catalog.review.intro")}</p>
      <ul className="grid list-disc gap-1 pl-5 text-sm">
        {problems.map((problem) => (
          <li key={problem}>{problem}</li>
        ))}
      </ul>
    </div>
  );
}

/** Moving to the trash asks first, on the page, saying the trash can restore it (16's 9.1). */
function DeleteButton({ part }: { part: PartDetails }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const remove = useDeletePart();
  const [asking, setAsking] = useState(false);

  if (!asking) {
    return (
      <button
        type="button"
        onClick={() => setAsking(true)}
        className="rounded-md border border-crit px-4 py-2 text-crit hover:bg-surface-2"
      >
        {t("catalog.part.delete")}
      </button>
    );
  }

  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm">{t("catalog.part.deleteQuestion")}</legend>
      {remove.isError &&
        (remove.error instanceof CatalogRefusal && remove.error.uses.length > 0 ? (
          <KeptByBoms refusal={remove.error} />
        ) : (
          <p role="alert" className="text-sm text-crit">
            {/* The only 409 without BOMs is the part's own stock, still on hand. */}
            {remove.error instanceof CatalogRefusal && remove.error.status === 409
              ? t("catalog.part.stocked")
              : t("catalog.part.deleteError")}
          </p>
        ))}
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={remove.isPending}
          onClick={() =>
            remove.mutate(part.id, { onSuccess: () => void navigate({ to: "/parts" }) })
          }
          className="rounded-md bg-crit px-4 py-2 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {t("catalog.part.deleteConfirm")}
        </button>
        <button
          type="button"
          onClick={() => setAsking(false)}
          className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
        >
          {t("catalog.part.deleteCancel")}
        </button>
      </div>
    </fieldset>
  );
}

/**
 * A move to the trash refused because bills of materials name the part: each of the first few
 * as a link to its revision, and how many more (09's requirement 11.13). A BOM whose project is
 * in the trash is named without a link, since its page can't be opened, and says where it is
 * (16's requirement 1.2). The sentence is built here, in the reader's language, from the uses
 * the API listed.
 */
function KeptByBoms({ refusal }: { refusal: CatalogRefusal }) {
  const { t } = useTranslation();
  const anyInTrash = refusal.uses.some((use) => use.in_trash);

  return (
    <div role="alert" className="grid gap-1 text-sm text-crit">
      <p>{t("catalog.part.inUse.intro")}</p>
      <ul className="grid list-disc gap-1 pl-5">
        {refusal.uses.map((use) => {
          const names = { project: use.project_name, revision: use.revision_label };
          return (
            <li key={use.revision_id}>
              {use.in_trash ? (
                t("catalog.part.inUse.bomInTrash", names)
              ) : (
                <Link
                  to="/projects/$projectId/revisions/$revisionId"
                  params={{ projectId: use.project_id, revisionId: use.revision_id }}
                  className="text-primary underline hover:opacity-80"
                >
                  {t("catalog.part.inUse.bom", names)}
                </Link>
              )}
            </li>
          );
        })}
      </ul>
      {refusal.more > 0 && <p>{t("catalog.part.inUse.more", { count: refusal.more })}</p>}
      {anyInTrash && <p>{t("catalog.part.inUse.trashNote")}</p>}
    </div>
  );
}

/** A stored value as it reads: engineering notation with its unit, yes or no for a switch. */
function shownValue(
  attribute: SchemaAttribute,
  stored: AttributeValue | undefined,
  t: TFunction,
): string | null {
  if (stored === undefined) return null;
  if (typeof stored.value === "boolean") {
    return stored.value ? t("catalog.part.yes") : t("catalog.part.no");
  }
  return `${stored.display}${attribute.unit ?? ""}`;
}
