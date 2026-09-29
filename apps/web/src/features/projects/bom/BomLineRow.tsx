import type { BomLine, BomPart } from "@wiredex/api-client";
import { type KeyboardEvent, type RefObject, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useRemoveBomLine, useUpdateBomLine } from "./bom";
import {
  bodyOf,
  bomCell,
  draftOf,
  FIELD_ORDER,
  type FieldErrors,
  LineCells,
  type LineDraft,
  LineFields,
  lineName,
  refusalOf,
  useLineFieldRefs,
  withoutChanged,
} from "./lineFields";

type Props = { revisionId: string; line: BomLine; part: BomPart | undefined };

const action = "rounded-md border border-border-strong px-2.5 py-1 text-sm hover:bg-surface-2";

/**
 * A line of a draft's BOM. *Edit line R1–R4* turns the row into the add row's fields, in
 * place: Enter saves, Escape puts the line back as it was, and either way focus returns to
 * *Edit* (requirement 11.5). *Remove line R1–R4* asks in the row first, focus on *Keep*, so
 * a stray Enter keeps the line (requirement 11.6).
 */
export function BomLineRow({ revisionId, line, part }: Props) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"view" | "edit" | "remove">("view");
  const editRef = useRef<HTMLButtonElement>(null);
  const removeRef = useRef<HTMLButtonElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  // Which control takes focus once the row has drawn its next mode.
  const [focusOn, setFocusOn] = useState<"edit" | "remove" | "keep" | "designators" | null>(null);
  const refs = useLineFieldRefs();
  const name = lineName(t, line, part);

  useEffect(() => {
    if (!focusOn) return;
    const target = {
      edit: editRef,
      remove: removeRef,
      keep: keepRef,
      designators: refs.designators,
    }[focusOn];
    target.current?.focus();
    setFocusOn(null);
  }, [focusOn, refs.designators]);

  function show(next: typeof mode, focus: NonNullable<typeof focusOn>) {
    setMode(next);
    setFocusOn(focus);
  }

  if (mode === "edit") {
    return (
      <EditingRow
        revisionId={revisionId}
        line={line}
        part={part}
        refs={refs}
        onDone={() => show("view", "edit")}
      />
    );
  }

  return (
    <tr className="border-b border-border">
      <LineCells line={line} part={part} />
      <td className={bomCell}>
        {mode === "view" ? (
          <div className="flex flex-wrap gap-2">
            <button
              ref={editRef}
              type="button"
              aria-label={t("projects.bom.editor.editLine", { name })}
              onClick={() => show("edit", "designators")}
              className={action}
            >
              {t("projects.bom.editor.edit")}
            </button>
            <button
              ref={removeRef}
              type="button"
              aria-label={t("projects.bom.editor.removeLine", { name })}
              onClick={() => show("remove", "keep")}
              className={`${action} border-crit text-crit`}
            >
              {t("projects.bom.editor.remove")}
            </button>
          </div>
        ) : (
          <RemoveQuestion
            revisionId={revisionId}
            line={line}
            name={name}
            keepRef={keepRef}
            onKeep={() => show("view", "remove")}
          />
        )}
      </td>
    </tr>
  );
}

type EditingProps = Props & {
  refs: ReturnType<typeof useLineFieldRefs>;
  onDone: () => void;
};

function EditingRow({ revisionId, line, part, refs, onDone }: EditingProps) {
  const { t } = useTranslation();
  const update = useUpdateBomLine();
  const [draft, setDraft] = useState<LineDraft>(() => draftOf(t, line, part));
  const [errors, setErrors] = useState<FieldErrors>({});
  const [rowError, setRowError] = useState<string | null>(null);
  const name = lineName(t, line, part);

  function save() {
    if (update.isPending) return;
    if (!draft.part) {
      setErrors({ part: t("projects.bom.editor.partNeeded") });
      refs.part.current?.focus();
      return;
    }
    update.mutate(
      { revisionId, lineId: line.id, body: bodyOf(draft, draft.part.id) },
      {
        onSuccess: onDone,
        onError: (error) => {
          const { fields, row } = refusalOf(t, error, t("projects.bom.editor.error"));
          setErrors(fields);
          setRowError(row);
          const first = FIELD_ORDER.find((field) => fields[field]);
          if (first) refs[first].current?.focus();
        },
      },
    );
  }

  function onKeyDown(event: KeyboardEvent<HTMLTableRowElement>) {
    // The part picker's own Enter and Escape, while its list is open, are already handled.
    if (event.isDefaultPrevented()) return;
    if (event.key === "Escape") {
      event.preventDefault();
      onDone();
    } else if (event.key === "Enter" && event.target instanceof HTMLInputElement) {
      event.preventDefault();
      save();
    }
  }

  return (
    <tr
      aria-label={t("projects.bom.editor.editing", { name })}
      onKeyDown={onKeyDown}
      className="border-b border-border bg-surface-2"
    >
      <LineFields
        draft={draft}
        onChange={(next) => {
          setErrors(withoutChanged(errors, draft, next));
          setDraft(next);
        }}
        errors={errors}
        refs={refs}
      />
      <td className={bomCell}>
        <div className="grid justify-items-start gap-1">
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={save}
              disabled={update.isPending}
              className="rounded-md bg-primary px-2.5 py-1 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
            >
              {update.isPending ? t("projects.bom.editor.saving") : t("projects.bom.editor.save")}
            </button>
            <button type="button" onClick={onDone} className={action}>
              {t("projects.bom.editor.cancel")}
            </button>
          </div>
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

type RemoveProps = {
  revisionId: string;
  line: BomLine;
  name: string;
  keepRef: RefObject<HTMLButtonElement | null>;
  onKeep: () => void;
};

function RemoveQuestion({ revisionId, line, name, keepRef, onKeep }: RemoveProps) {
  const { t } = useTranslation();
  const remove = useRemoveBomLine();

  return (
    <fieldset
      className="grid gap-2"
      aria-label={t("projects.bom.editor.removeQuestionOf", { name })}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onKeep();
        }
      }}
    >
      <legend className="text-sm">{t("projects.bom.editor.removeQuestion")}</legend>
      {remove.isError && (
        <p role="alert" className="text-sm text-crit">
          {refusalOf(t, remove.error, t("projects.bom.editor.removeError")).row ??
            t("projects.bom.editor.removeError")}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={remove.isPending}
          onClick={() => remove.mutate({ revisionId, lineId: line.id })}
          className="rounded-md bg-crit px-2.5 py-1 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {t("projects.bom.editor.removeConfirm")}
        </button>
        <button ref={keepRef} type="button" onClick={onKeep} className={action}>
          {t("projects.bom.editor.keep")}
        </button>
      </div>
    </fieldset>
  );
}
