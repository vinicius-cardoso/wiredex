import { type KeyboardEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAddBomLine } from "./bom";
import {
  bodyOf,
  bomCell,
  emptyDraft,
  FIELD_ORDER,
  type FieldErrors,
  type LineDraft,
  LineFields,
  refusalOf,
  useLineFieldRefs,
  withoutChanged,
} from "./lineFields";

/**
 * The table's last row, which adds a line (requirement 11.2, design decision 17): Designators,
 * Part, Quantity and Notes, and Enter adds from any of them. Once the line is added the row
 * clears and Designators takes focus again, so a schematic goes in as *R1-4, Tab, 4k7, Enter*
 * over and over. A refusal lands on the field it names, which takes focus (requirement 11.7).
 */
export function BomAddRow({ revisionId }: { revisionId: string }) {
  const { t } = useTranslation();
  const add = useAddBomLine();
  const refs = useLineFieldRefs();
  const [draft, setDraft] = useState<LineDraft>(emptyDraft);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [rowError, setRowError] = useState<string | null>(null);

  function refuse(fields: FieldErrors, row: string | null) {
    setErrors(fields);
    setRowError(row);
    const first = FIELD_ORDER.find((field) => fields[field]);
    if (first) refs[first].current?.focus();
  }

  function submit() {
    if (add.isPending) return;
    // Checked here, since the API can't say which part was meant when none was sent.
    if (!draft.part) {
      refuse({ part: t("projects.bom.editor.partNeeded") }, null);
      return;
    }
    add.mutate(
      { revisionId, body: bodyOf(draft, draft.part.id) },
      {
        onSuccess: () => {
          setDraft(emptyDraft);
          setErrors({});
          setRowError(null);
          refs.designators.current?.focus();
        },
        onError: (error) => {
          const { fields, row } = refusalOf(t, error, t("projects.bom.editor.error"));
          refuse(fields, row);
        },
      },
    );
  }

  function onKeyDown(event: KeyboardEvent<HTMLTableRowElement>) {
    // A field's own Enter, such as the part picker picking, has already been handled.
    if (event.key !== "Enter" || event.isDefaultPrevented()) return;
    if (!(event.target instanceof HTMLInputElement)) return;
    event.preventDefault();
    submit();
  }

  return (
    <tr aria-label={t("projects.bom.editor.newLine")} onKeyDown={onKeyDown}>
      <LineFields
        draft={draft}
        onChange={(next) => {
          setErrors(withoutChanged(errors, draft, next));
          setDraft(next);
        }}
        errors={errors}
        refs={refs}
      />
      <td className={bomCell} colSpan={2}>
        <div className="grid justify-items-start gap-1">
          <button
            type="button"
            onClick={submit}
            disabled={add.isPending}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold whitespace-nowrap text-on-primary hover:opacity-90 disabled:opacity-60"
          >
            {add.isPending ? t("projects.bom.editor.adding") : t("projects.bom.editor.add")}
          </button>
          {rowError && (
            <p role="alert" className="text-sm text-crit">
              {rowError}
            </p>
          )}
        </div>
      </td>
    </tr>
  );
}
