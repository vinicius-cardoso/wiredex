import { Link } from "@tanstack/react-router";
import type { ImportPreview, ImportResult, ImportSummary } from "@wiredex/api-client";
import type { TFunction } from "i18next";
import { type ChangeEvent, type RefObject, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ImportPreviewTable, ProblemList } from "./ImportPreviewTable";
import { IMPORT_TEMPLATE_URL, IntakeRefusal, useImportSheet, usePreviewImport } from "./intake";

// The API's cap on a sheet (design decision 10), counted as it counts: in characters, not in
// UTF-16 halves. Checked here too, so a sheet it would refuse for its size never goes out.
const MAX_CHARACTERS = 262_144;

const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";
const secondary =
  "rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2 disabled:opacity-60";
const primary =
  "rounded-md bg-primary px-4 py-2 font-semibold text-on-primary hover:opacity-90 aria-disabled:cursor-not-allowed aria-disabled:opacity-60";

/** A preview, and the text it was made for: the only text it lets be imported. */
type Previewed = { csv: string; plan: ImportPreview };

/** Why an import went nowhere, and whether previewing again is the way on. */
type Refused = { message: string; problems: IntakeRefusal["problems"]; again: boolean };

/**
 * The import page (requirement 11.1 to 11.5): a sheet chosen as a file or pasted, previewed,
 * fixed in place and previewed again, then imported whole.
 *
 * A chosen file only fills the text box, so a bad cell is fixed right here rather than in the
 * spreadsheet. *Import* is offered only for a clean preview of the text exactly as it stands:
 * any edit since the preview turns it off again, with the reason next to it (11.3). It stays a
 * focusable button marked `aria-disabled`, so a keyboard user reaches it and hears why. The
 * summary of a preview, or of an import, is announced through one polite live region.
 */
export function ImportPage() {
  const { t } = useTranslation();
  const fileId = useId();
  const fileHintId = useId();
  const textId = useId();
  const textHintId = useId();
  const reasonId = useId();

  const preview = usePreviewImport();
  const importSheet = useImportSheet();

  const [text, setText] = useState("");
  const [previewed, setPreviewed] = useState<Previewed | null>(null);
  const [inputError, setInputError] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [refused, setRefused] = useState<Refused | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  const importRef = useRef<HTMLButtonElement>(null);
  const previewHeadingRef = useRef<HTMLHeadingElement>(null);
  const againRef = useRef<HTMLButtonElement>(null);
  const resultHeadingRef = useRef<HTMLHeadingElement>(null);

  const blocked = blockedReason(previewed, text, t);

  async function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      // Decoded as UTF-8: bytes that aren't come through as U+FFFD, which the API refuses
      // as `not_utf8`, so a sheet saved in another encoding is caught at its preview.
      setText(await file.text());
      setInputError(null);
    } catch {
      setInputError(t("inventory.import.fileError"));
    }
  }

  function runPreview() {
    if (preview.isPending) return;
    if (text.trim() === "") {
      setInputError(t("inventory.import.empty"));
      return;
    }
    if ([...text].length > MAX_CHARACTERS) {
      setInputError(t("inventory.import.tooLong", { max: MAX_CHARACTERS }));
      return;
    }
    const csv = text;
    setInputError(null);
    setPreviewError(null);
    setRefused(null);
    setResult(null);
    preview.mutate(csv, {
      onSuccess: (plan) => {
        setPreviewed({ csv, plan });
        // A clean preview's next step is *Import*; one with problems is read first.
        requestAnimationFrame(() => {
          if (isClean(plan)) importRef.current?.focus();
          else previewHeadingRef.current?.focus();
        });
      },
      onError: (error) => {
        setPreviewed(null);
        setPreviewError(previewRefusalText(error, t));
      },
    });
  }

  function runImport() {
    if (blocked !== null || !previewed || importSheet.isPending) return;
    setRefused(null);
    importSheet.mutate(
      { csv: previewed.csv, digest: previewed.plan.digest },
      {
        onSuccess: (imported) => {
          setResult(imported);
          // Done: importing again would stock the sheet a second time, so that takes a new
          // preview, deliberately.
          setPreviewed(null);
          requestAnimationFrame(() => resultHeadingRef.current?.focus());
        },
        onError: (error) => {
          setRefused(importRefusal(error, t));
          requestAnimationFrame(() => againRef.current?.focus());
        },
      },
    );
  }

  return (
    <section className="grid gap-6">
      <div className="grid gap-2">
        <h1 className="font-display text-2xl font-semibold tracking-tight">
          {t("inventory.import.title")}
        </h1>
        <p className="max-w-prose text-muted">{t("inventory.import.intro")}</p>
        <p className="max-w-prose text-sm text-muted">{t("inventory.import.columns")}</p>
      </div>

      <div className="grid max-w-3xl gap-4">
        <h2 className="font-display text-xl font-semibold">{t("inventory.import.sheet")}</h2>
        <div className="grid gap-1">
          <label htmlFor={fileId} className="text-sm font-medium">
            {t("inventory.import.file")}
          </label>
          <input
            id={fileId}
            type="file"
            accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values,text/plain"
            aria-describedby={fileHintId}
            onChange={(event) => void chooseFile(event)}
            className="text-sm file:mr-3 file:rounded-md file:border file:border-border-strong file:bg-surface file:px-3 file:py-1.5 file:text-text"
          />
          <p id={fileHintId} className="text-sm text-muted">
            {t("inventory.import.fileHint")}
          </p>
        </div>
        <div className="grid gap-1">
          <label htmlFor={textId} className="text-sm font-medium">
            {t("inventory.import.text")}
          </label>
          <textarea
            id={textId}
            value={text}
            onChange={(event) => setText(event.target.value)}
            rows={10}
            spellCheck={false}
            aria-describedby={textHintId}
            aria-invalid={inputError ? true : undefined}
            className={`${control} font-mono text-sm`}
          />
          <p id={textHintId} className="text-sm text-muted">
            {t("inventory.import.textHint")}
          </p>
        </div>
        {inputError && (
          <p role="alert" className="text-sm text-crit">
            {inputError}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={runPreview}
            disabled={preview.isPending}
            className={secondary}
          >
            {preview.isPending ? t("inventory.import.previewing") : t("inventory.import.preview")}
          </button>
          <a href={IMPORT_TEMPLATE_URL} download="wiredex-import.csv" className={secondary}>
            {t("inventory.import.template")}
          </a>
        </div>
        {previewError && (
          <p role="alert" className="rounded-md border border-crit px-3 py-2 text-sm text-crit">
            {previewError}
          </p>
        )}
      </div>

      {/* Always there, so a summary is announced when it arrives. */}
      <div role="status" aria-label={t("inventory.import.summaryLabel")} className="grid gap-2">
        {result && <SummaryPanel summary={result.summary} lead={t("inventory.import.imported")} />}
        {!result && previewed && (
          <SummaryPanel
            summary={previewed.plan.summary}
            lead={
              isClean(previewed.plan) ? t("inventory.import.clean") : t("inventory.import.problems")
            }
          />
        )}
      </div>

      {previewed && (
        <div className="grid gap-1">
          <div>
            <button
              ref={importRef}
              type="button"
              onClick={runImport}
              aria-disabled={blocked !== null || importSheet.isPending ? true : undefined}
              aria-describedby={blocked ? reasonId : undefined}
              className={primary}
            >
              {importSheet.isPending
                ? t("inventory.import.importing")
                : t("inventory.import.submit")}
            </button>
          </div>
          {blocked && (
            <p id={reasonId} className="text-sm text-muted">
              {blocked}
            </p>
          )}
        </div>
      )}

      {refused && <RefusedPanel refused={refused} againRef={againRef} onAgain={runPreview} />}

      {result && <ResultPanel result={result} headingRef={resultHeadingRef} />}

      {previewed && (
        <div className="grid gap-3">
          <h2
            ref={previewHeadingRef}
            tabIndex={-1}
            className="font-display text-xl font-semibold focus:outline-none"
          >
            {t("inventory.import.table.heading")}
          </h2>
          <ImportPreviewTable preview={previewed.plan} />
        </div>
      )}
    </section>
  );
}

function SummaryPanel({ summary, lead }: { summary: ImportSummary; lead: string }) {
  const { t } = useTranslation();
  const entries: [string, number][] = [
    [t("inventory.import.summary.rows"), summary.rows],
    [t("inventory.import.summary.newParts"), summary.new_parts],
    [t("inventory.import.summary.existingParts"), summary.existing_parts],
    [t("inventory.import.summary.receipts"), summary.receipts],
    [t("inventory.import.summary.pieces"), summary.pieces],
    [t("inventory.import.summary.units"), summary.units],
    [t("inventory.import.summary.rowsWithProblems"), summary.rows_with_problems],
  ];
  return (
    <>
      <p className="font-semibold">{lead}</p>
      <dl className="grid max-w-md grid-cols-[1fr_auto] gap-x-6 gap-y-1 rounded-lg border border-border bg-surface p-4 text-sm">
        {entries.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted">{label}</dt>
            <dd className="text-right tabular-nums">{t("inventory.import.count", { value })}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}

type RefusedProps = {
  refused: Refused;
  againRef: RefObject<HTMLButtonElement | null>;
  onAgain: () => void;
};

/** An import that wrote nothing: why, and *Preview again* when that is the way on (11.4). */
function RefusedPanel({ refused, againRef, onAgain }: RefusedProps) {
  const { t } = useTranslation();
  return (
    <div className="grid max-w-3xl justify-items-start gap-2 rounded-md border border-crit px-3 py-2">
      <p role="alert" className="text-sm text-crit">
        {refused.message}
      </p>
      {refused.problems.length > 0 && <ProblemList problems={refused.problems} />}
      {refused.again && (
        <button ref={againRef} type="button" onClick={onAgain} className={secondary}>
          {t("inventory.import.previewAgain")}
        </button>
      )}
    </div>
  );
}

type ResultProps = { result: ImportResult; headingRef: RefObject<HTMLHeadingElement | null> };

/** What the import did: the parts it defined, by row, and every unit code it minted (11.5). */
function ResultPanel({ result, headingRef }: ResultProps) {
  const { t } = useTranslation();
  return (
    <div className="grid gap-3">
      <h2
        ref={headingRef}
        tabIndex={-1}
        className="font-display text-xl font-semibold focus:outline-none"
      >
        {t("inventory.import.result.heading")}
      </h2>
      {result.parts.length > 0 && (
        <div className="grid gap-1">
          <h3 className="font-semibold">{t("inventory.import.result.parts")}</h3>
          <ul aria-label={t("inventory.import.result.parts")} className="grid gap-1 text-sm">
            {result.parts.map((part) => (
              <li key={part.part_id}>
                <Link
                  to="/parts/$partId"
                  params={{ partId: part.part_id }}
                  className="text-primary underline"
                >
                  {t("inventory.import.result.part", { row: part.row, name: part.name })}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
      {result.units.length > 0 && (
        <div className="grid gap-1">
          <h3 className="font-semibold">{t("inventory.import.result.codes")}</h3>
          <ul aria-label={t("inventory.import.result.codes")} className="grid gap-1 text-sm">
            {result.units.map((unit) => (
              <li key={unit.id}>
                <Link
                  to="/units/$unitId"
                  params={{ unitId: unit.id }}
                  className="font-mono text-primary underline"
                >
                  {unit.code}
                </Link>
                <span className="text-muted">
                  {" "}
                  {[unit.serial, unit.mac, unit.location?.code].filter(Boolean).join(" · ")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function isClean(plan: ImportPreview): boolean {
  return plan.problems.length === 0 && plan.rows.every((row) => row.problems.length === 0);
}

/** Why *Import* is off, or null when the text as it stands has a clean preview (11.3). */
function blockedReason(previewed: Previewed | null, text: string, t: TFunction): string | null {
  if (!previewed) return t("inventory.import.blocked.notPreviewed");
  if (previewed.csv !== text) return t("inventory.import.blocked.stale");
  if (!isClean(previewed.plan)) return t("inventory.import.blocked.problems");
  if (previewed.plan.rows.length === 0) return t("inventory.import.blocked.nothing");
  return null;
}

/** An unreadable sheet in the reader's language (4.6); anything else in the server's words. */
function previewRefusalText(error: unknown, t: TFunction): string {
  if (error instanceof IntakeRefusal && error.sheet) {
    return t(`inventory.import.refusal.${error.sheet.code}`, { column: error.sheet.column ?? "" });
  }
  if (error instanceof IntakeRefusal && error.detail) return error.detail;
  return t("inventory.import.error.preview");
}

function importRefusal(error: unknown, t: TFunction): Refused {
  const refusal = error instanceof IntakeRefusal ? error : null;
  // A changed outcome (8.3), or a balance that lost a race: nothing was written, and a new
  // preview shows what the sheet would do now.
  if (refusal?.status === 409) {
    return { message: t("inventory.import.changed"), problems: [], again: true };
  }
  if (refusal && refusal.problems.length > 0) {
    return { message: t("inventory.import.refused"), problems: refusal.problems, again: true };
  }
  return {
    message: refusal?.detail || t("inventory.import.error.import"),
    problems: [],
    again: false,
  };
}
