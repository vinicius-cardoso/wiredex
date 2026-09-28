import type { ProjectDetails, RevisionDetails } from "@wiredex/api-client";
import type { TFunction } from "i18next";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { control, dialogPrimary, StockDialog } from "../inventory/StockDialog";
import {
  ProjectRefusal,
  revisionName,
  useAddRevision,
  useForkRevision,
  useUpdateRevision,
} from "./projects";

/** The server's rules (requirements 4.2, 4.7), checked here so the dialog says so first. */
const LABEL = /^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,14}[A-Za-z0-9])?$/;
const MAX_SUMMARY_LENGTH = 120;
const MAX_NOTES_LENGTH = 4_000;

type Values = { label: string; summary: string; notes: string };

/** What the three dialogs send: blank texts as none, as the API reads them. */
type Sent = { label: string | null; summary: string | null; notes: string | null };

type FieldsProps = {
  title: string;
  initial: Values;
  /** An edit must keep a label; a new revision or a fork may leave it to the suggestion. */
  labelRequired: boolean;
  confirm: string;
  pending: boolean;
  error: unknown;
  onSubmit: (sent: Sent) => void;
  onClose: () => void;
};

/**
 * The label, summary and notes every revision dialog asks for, on 05's dialog shell. Enter
 * in the label or the summary submits, as any form does; a 409 is always the label another
 * revision holds, so it lands on the label (requirement 4.3).
 */
function RevisionFields({
  title,
  initial,
  labelRequired,
  confirm,
  pending,
  error,
  onSubmit,
  onClose,
}: FieldsProps) {
  const { t } = useTranslation();
  const labelId = useId();
  const summaryId = useId();
  const notesId = useId();
  const [values, setValues] = useState(initial);
  const [problems, setProblems] = useState<Partial<Values>>({});

  const refusal = error instanceof ProjectRefusal ? error : null;
  const labelProblem =
    problems.label ?? (refusal?.status === 409 ? refusal.detail || undefined : undefined);
  const otherRefusal =
    error && refusal?.status !== 409
      ? refusal?.detail || t("projects.revisionDialog.error.save")
      : null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = problemsOf(values, labelRequired, t);
    setProblems(found);
    if (Object.keys(found).length > 0) return;
    const label = values.label.trim();
    const summary = collapsed(values.summary);
    const notes = plain(values.notes);
    onSubmit({
      label: label === "" ? null : label,
      summary: summary === "" ? null : summary,
      notes: notes === "" ? null : notes,
    });
  }

  function field(name: keyof Values) {
    return {
      value: values[name],
      onChange: (event: { target: { value: string } }) =>
        setValues((current) => ({ ...current, [name]: event.target.value })),
    };
  }

  return (
    <StockDialog title={title} onClose={onClose}>
      <form noValidate onSubmit={submit} className="grid gap-3">
        <div className="grid gap-1">
          <label htmlFor={labelId} className="text-sm font-medium">
            {t("projects.revisionDialog.label")}
          </label>
          <input
            id={labelId}
            type="text"
            autoComplete="off"
            className={control}
            aria-required={labelRequired}
            aria-invalid={labelProblem ? true : undefined}
            aria-describedby={`${labelId}-hint${labelProblem ? ` ${labelId}-error` : ""}`}
            {...field("label")}
          />
          <p id={`${labelId}-hint`} className="text-sm text-muted">
            {t("projects.revisionDialog.labelHint")}
          </p>
          {labelProblem && (
            <p id={`${labelId}-error`} className="text-sm text-crit">
              {labelProblem}
            </p>
          )}
        </div>

        <div className="grid gap-1">
          <label htmlFor={summaryId} className="text-sm font-medium">
            {t("projects.revisionDialog.summary")}
          </label>
          <input
            id={summaryId}
            type="text"
            autoComplete="off"
            placeholder={t("projects.revisionDialog.summaryPlaceholder")}
            className={control}
            aria-invalid={problems.summary ? true : undefined}
            {...(problems.summary ? { "aria-describedby": `${summaryId}-error` } : {})}
            {...field("summary")}
          />
          {problems.summary && (
            <p id={`${summaryId}-error`} className="text-sm text-crit">
              {problems.summary}
            </p>
          )}
        </div>

        <div className="grid gap-1">
          <label htmlFor={notesId} className="text-sm font-medium">
            {t("projects.revisionDialog.notes")}
          </label>
          <textarea
            id={notesId}
            rows={4}
            className={control}
            aria-invalid={problems.notes ? true : undefined}
            {...(problems.notes ? { "aria-describedby": `${notesId}-error` } : {})}
            {...field("notes")}
          />
          {problems.notes && (
            <p id={`${notesId}-error`} className="text-sm text-crit">
              {problems.notes}
            </p>
          )}
        </div>

        {otherRefusal && (
          <p role="alert" className="text-sm text-crit">
            {otherRefusal}
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={pending} className={dialogPrimary}>
            {confirm}
          </button>
          <button type="button" onClick={onClose} className={control}>
            {t("projects.revisionDialog.cancel")}
          </button>
        </div>
      </form>
    </StockDialog>
  );
}

type NewProps = {
  project: ProjectDetails;
  onClose: () => void;
  onCreated: (revision: RevisionDetails) => void;
};

/** A new draft of the project, its label prefilled with the suggestion (requirement 10.6). */
export function NewRevisionDialog({ project, onClose, onCreated }: NewProps) {
  const { t } = useTranslation();
  const add = useAddRevision();

  return (
    <RevisionFields
      title={t("projects.revisionDialog.newTitle", { project: project.name })}
      initial={{ label: project.next_label ?? "", summary: "", notes: "" }}
      labelRequired={false}
      confirm={t("projects.revisionDialog.create")}
      pending={add.isPending}
      error={add.error}
      onSubmit={(body) => add.mutate({ projectId: project.id, body }, { onSuccess: onCreated })}
      onClose={onClose}
    />
  );
}

type ForkProps = {
  project: ProjectDetails;
  source: RevisionDetails;
  onClose: () => void;
  onForked: (revision: RevisionDetails) => void;
};

/**
 * A fork of SOURCE: a new draft carrying its content (requirement 6.1), the label prefilled
 * with the project's `next_label`, the one the API would pick anyway.
 */
export function ForkRevisionDialog({ project, source, onClose, onForked }: ForkProps) {
  const { t } = useTranslation();
  const fork = useForkRevision();

  return (
    <RevisionFields
      title={t("projects.revisionDialog.forkTitle", { name: revisionName(t, source) })}
      initial={{ label: project.next_label ?? "", summary: "", notes: "" }}
      labelRequired={false}
      confirm={t("projects.revisionDialog.fork")}
      pending={fork.isPending}
      error={fork.error}
      onSubmit={(body) => fork.mutate({ revisionId: source.id, body }, { onSuccess: onForked })}
      onClose={onClose}
    />
  );
}

type EditProps = { revision: RevisionDetails; onClose: () => void };

/** A revision's label, summary and notes, replaced whatever its status (requirement 4.8). */
export function EditRevisionDialog({ revision, onClose }: EditProps) {
  const { t } = useTranslation();
  const update = useUpdateRevision();

  return (
    <RevisionFields
      title={t("projects.revisionDialog.editTitle", { name: revisionName(t, revision) })}
      initial={{
        label: revision.label,
        summary: revision.summary ?? "",
        notes: revision.notes ?? "",
      }}
      labelRequired={true}
      confirm={t("projects.revisionDialog.save")}
      pending={update.isPending}
      error={update.error}
      onSubmit={({ label, summary, notes }) =>
        update.mutate(
          // The label is required here, so problemsOf has already refused a blank one.
          { revisionId: revision.id, body: { label: label ?? revision.label, summary, notes } },
          { onSuccess: onClose },
        )
      }
      onClose={onClose}
    />
  );
}

function problemsOf(values: Values, labelRequired: boolean, t: TFunction): Partial<Values> {
  const problems: Partial<Values> = {};
  const label = values.label.trim();
  if (label === "") {
    if (labelRequired) problems.label = t("projects.revisionDialog.error.labelRequired");
  } else if (!LABEL.test(label)) {
    problems.label = t("projects.revisionDialog.error.label");
  }
  if ([...collapsed(values.summary)].length > MAX_SUMMARY_LENGTH) {
    problems.summary = t("projects.form.error.tooLong", { max: MAX_SUMMARY_LENGTH });
  }
  if ([...plain(values.notes)].length > MAX_NOTES_LENGTH) {
    problems.notes = t("projects.form.error.tooLong", { max: MAX_NOTES_LENGTH });
  }
  return problems;
}

/** Whitespace collapsed, as the server reads a summary (requirement 4.7). */
function collapsed(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ");
}

/** Line breaks unified and ends trimmed, as the server reads notes (requirement 4.7). */
function plain(text: string): string {
  return text.replace(/\r\n?/g, "\n").trim();
}
