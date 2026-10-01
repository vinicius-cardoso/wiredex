import type { FirmwareDetails, FirmwareField, FirmwareVersion } from "@wiredex/api-client";
import type { TFunction } from "i18next";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { control, dialogPrimary, StockDialog } from "../inventory/StockDialog";
import { FirmwareRefusal, useReleaseVersion, useStartVersion, useUpdateVersion } from "./firmware";
import { refusalKey, statusKey } from "./labels";

/** The server's grammar (requirement 5.1), checked here so the dialog says so first. */
const NUMBER = "(?:0|[1-9][0-9]*)";
const IDENTIFIER = `(?:${NUMBER}|[0-9]*[A-Za-z-][0-9A-Za-z-]*)`;
const SEMVER = new RegExp(
  `^${NUMBER}\\.${NUMBER}\\.${NUMBER}(?:-${IDENTIFIER}(?:\\.${IDENTIFIER})*)?$`,
);
const MAX_VERSION_LENGTH = 64;
const MAX_CHANGELOG_LENGTH = 4_000;

/** The fields a version dialog shows a refusal on. */
type DialogField = Extract<FirmwareField, "version" | "changelog">;
type Problems = Partial<Record<DialogField, string>>;

type NewProps = {
  firmware: FirmwareDetails;
  /** The version it was started from, which *Start from* offers first (requirement 11.8). */
  from: string | null;
  onClose: () => void;
  onStarted: (version: FirmwareVersion) => void;
};

/**
 * A new draft (requirement 11.8): the number prefilled with the firmware's suggestion, and
 * *Start from* on the version it was opened from, or else the highest, with an empty version
 * as a choice. A blank number takes the suggestion, as the API reads it (requirement 5.4).
 */
export function NewVersionDialog({ firmware, from, onClose, onStarted }: NewProps) {
  const { t } = useTranslation();
  const start = useStartVersion();
  const numberId = useId();
  const fromId = useId();
  const [number, setNumber] = useState(firmware.suggested_version);
  const [base, setBase] = useState(from ?? firmware.versions[0]?.id ?? "");
  const [problems, setProblems] = useState<Problems>({});
  const refused = refusalOf(t, start.error, "firmware.version.dialog.error.save");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = numberProblems(number, false, t);
    setProblems(found);
    if (Object.keys(found).length > 0) return;
    const version = number.trim();
    start.mutate(
      {
        firmwareId: firmware.id,
        body: { version: version === "" ? null : version, from_version_id: base || null },
      },
      { onSuccess: onStarted },
    );
  }

  return (
    <StockDialog
      title={t("firmware.version.dialog.newTitle", { name: firmware.name })}
      onClose={onClose}
    >
      <form noValidate onSubmit={submit} className="grid gap-3">
        <NumberField
          id={numberId}
          value={number}
          onChange={setNumber}
          required={false}
          problem={problems.version ?? refused.fields.version}
        />

        <div className="grid gap-1">
          <label htmlFor={fromId} className="text-sm font-medium">
            {t("firmware.version.dialog.from")}
          </label>
          <select
            id={fromId}
            value={base}
            onChange={(event) => setBase(event.target.value)}
            aria-describedby={`${fromId}-hint`}
            className={control}
          >
            {firmware.versions.map((version) => (
              <option key={version.id} value={version.id}>
                {t("firmware.page.versionEntry", {
                  version: version.version,
                  status: t(statusKey(version.status)),
                })}
              </option>
            ))}
            <option value="">{t("firmware.version.dialog.empty")}</option>
          </select>
          <p id={`${fromId}-hint`} className="text-sm text-muted">
            {t("firmware.version.dialog.fromHint")}
          </p>
        </div>

        {refused.form && (
          <p role="alert" className="text-sm text-crit">
            {refused.form}
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={start.isPending} className={dialogPrimary}>
            {t("firmware.version.dialog.create")}
          </button>
          <button type="button" onClick={onClose} className={control}>
            {t("firmware.version.dialog.cancel")}
          </button>
        </div>
      </form>
    </StockDialog>
  );
}

type EditProps = {
  version: FirmwareVersion;
  onClose: () => void;
  onSaved: (version: FirmwareVersion) => void;
};

/** A draft's number and changelog, replaced whole (requirement 5.7). */
export function EditVersionDialog({ version, onClose, onSaved }: EditProps) {
  const { t } = useTranslation();
  const update = useUpdateVersion();
  const numberId = useId();
  const changelogId = useId();
  const [number, setNumber] = useState(version.version);
  const [changelog, setChangelog] = useState(version.changelog ?? "");
  const [problems, setProblems] = useState<Problems>({});
  const refused = refusalOf(t, update.error, "firmware.version.dialog.error.save");
  const changelogProblem = problems.changelog ?? refused.fields.changelog;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = numberProblems(number, true, t);
    const text = plain(changelog);
    if ([...text].length > MAX_CHANGELOG_LENGTH) {
      found.changelog = t("firmware.version.dialog.error.tooLong", { max: MAX_CHANGELOG_LENGTH });
    }
    setProblems(found);
    if (Object.keys(found).length > 0) return;
    update.mutate(
      // A cleared changelog is none, never a refusal (requirement 5.6).
      { versionId: version.id, body: { version: number.trim(), changelog: text || null } },
      { onSuccess: onSaved },
    );
  }

  return (
    <StockDialog
      title={t("firmware.version.dialog.editTitle", { version: version.version })}
      onClose={onClose}
    >
      <form noValidate onSubmit={submit} className="grid gap-3">
        <NumberField
          id={numberId}
          value={number}
          onChange={setNumber}
          required={true}
          problem={problems.version ?? refused.fields.version}
        />

        <div className="grid gap-1">
          <label htmlFor={changelogId} className="text-sm font-medium">
            {t("firmware.version.changelog")}
          </label>
          <textarea
            id={changelogId}
            rows={5}
            value={changelog}
            onChange={(event) => setChangelog(event.target.value)}
            className={control}
            aria-invalid={changelogProblem ? true : undefined}
            aria-describedby={`${changelogId}-hint${changelogProblem ? ` ${changelogId}-error` : ""}`}
          />
          <p id={`${changelogId}-hint`} className="text-sm text-muted">
            {t("firmware.version.dialog.changelogHint")}
          </p>
          {changelogProblem && (
            <p id={`${changelogId}-error`} className="text-sm text-crit">
              {changelogProblem}
            </p>
          )}
        </div>

        {refused.form && (
          <p role="alert" className="text-sm text-crit">
            {refused.form}
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={update.isPending} className={dialogPrimary}>
            {t("firmware.version.dialog.save")}
          </button>
          <button type="button" onClick={onClose} className={control}>
            {t("firmware.version.dialog.cancel")}
          </button>
        </div>
      </form>
    </StockDialog>
  );
}

type ReleaseProps = { version: FirmwareVersion; onClose: () => void; onReleased: () => void };

/** Releasing asks first, saying what it freezes (requirement 11.7). */
export function ReleaseDialog({ version, onClose, onReleased }: ReleaseProps) {
  const { t } = useTranslation();
  const release = useReleaseVersion();
  const refused = refusalOf(t, release.error, "firmware.version.dialog.error.release");
  // A release refusal names no field the dialog shows, so every one is the dialog's own.
  const problem = refused.form ?? refused.fields.changelog ?? refused.fields.version;

  return (
    <StockDialog
      title={t("firmware.version.dialog.releaseTitle", { version: version.version })}
      onClose={onClose}
    >
      <p>{t("firmware.version.dialog.releaseWarning")}</p>
      {problem && (
        <p role="alert" className="text-sm text-crit">
          {problem}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={release.isPending}
          onClick={() => release.mutate(version.id, { onSuccess: onReleased })}
          className={dialogPrimary}
        >
          {t("firmware.version.dialog.releaseConfirm", { version: version.version })}
        </button>
        <button type="button" onClick={onClose} className={control}>
          {t("firmware.version.dialog.cancel")}
        </button>
      </div>
    </StockDialog>
  );
}

type NumberFieldProps = {
  id: string;
  value: string;
  onChange: (value: string) => void;
  /** An edit must keep a number; a new version may leave it to the suggestion. */
  required: boolean;
  problem: string | undefined;
};

function NumberField({ id, value, onChange, required, problem }: NumberFieldProps) {
  const { t } = useTranslation();
  return (
    <div className="grid gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {t("firmware.version.dialog.number")}
      </label>
      <input
        id={id}
        type="text"
        autoComplete="off"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={`${control} font-mono`}
        aria-required={required}
        aria-invalid={problem ? true : undefined}
        aria-describedby={`${id}-hint${problem ? ` ${id}-error` : ""}`}
      />
      <p id={`${id}-hint`} className="text-sm text-muted">
        {t("firmware.version.dialog.numberHint")}
      </p>
      {problem && (
        <p id={`${id}-error`} className="text-sm text-crit">
          {problem}
        </p>
      )}
    </div>
  );
}

function numberProblems(text: string, required: boolean, t: TFunction): Problems {
  const number = text.trim();
  if (number === "") {
    return required ? { version: t("firmware.version.dialog.error.numberRequired") } : {};
  }
  const bare = number.startsWith("v") ? number.slice(1) : number;
  if (bare.length > MAX_VERSION_LENGTH || !SEMVER.test(bare)) {
    return { version: t("firmware.version.dialog.error.number") };
  }
  return {};
}

/**
 * A refused write, as the sentences the dialog shows: on the field it names, from its code
 * (requirement 5.2's taken number lands on the number); a 404 says the version is gone; the
 * rest is the dialog's own, the API's sentence when no code of ours fits.
 */
function refusalOf(
  t: TFunction,
  error: unknown,
  fallback: "firmware.version.dialog.error.save" | "firmware.version.dialog.error.release",
): { fields: Problems; form: string | null } {
  if (!error) return { fields: {}, form: null };
  const refusal = error instanceof FirmwareRefusal ? error : null;
  if (refusal?.status === 404) {
    return { fields: {}, form: t("firmware.version.dialog.error.gone") };
  }
  const key = refusalKey(refusal?.code ?? null);
  const sentence = key ? t(key, { item: refusal?.item ?? "" }) : t(fallback);
  const field = refusal?.field;
  if (field === "version" || field === "changelog") {
    return { fields: { [field]: sentence }, form: null };
  }
  return { fields: {}, form: sentence };
}

/** Line breaks unified and ends trimmed, as the server reads a changelog (requirement 5.6). */
function plain(text: string): string {
  return text.replace(/\r\n?/g, "\n").trim();
}
