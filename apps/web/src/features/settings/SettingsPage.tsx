import { Link } from "@tanstack/react-router";
import type { Preferences } from "@wiredex/api-client";
import { type ReactNode, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Block, PageGrid } from "../../shared/ui/block";
import { formatsOf } from "./formats";
import { usePreferences, useUpdatePreferences } from "./preferences";

const BASES = ["free", "total"] as const satisfies readonly Preferences["stock_basis"][];
const DATE_FORMATS = [
  "language",
  "iso",
  "dmy",
  "mdy",
] as const satisfies readonly Preferences["date_format"][];
const NUMBER_FORMATS = [
  "language",
  "point",
  "comma",
] as const satisfies readonly Preferences["number_format"][];
/** The retentions offered; none keeps the trash until it is emptied by hand. */
const RETENTIONS = [null, 7, 14, 30, 60, 90, 180, 365] as const;
const MAX_MINIMUM_STOCK = 1_000_000;
const PREFIX = /^[A-Za-z][A-Za-z0-9]{0,5}$/;
/** A fixed instant to show each format with: the example reads the same for every reader. */
const EXAMPLE_DATE = new Date(2026, 9, 11, 14, 30);
const EXAMPLE_NUMBER = 1234.5;

const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";

type Save = (change: Partial<Preferences>) => void;

/**
 * The workspace's settings (specs 24 and 25): choices that change what its pages answer, kept
 * on the server so every device agrees. Each is saved as it is changed, and the page says it
 * saved, or that it couldn't and what is kept. The theme and the language stay in the header,
 * where they are a click away.
 */
export function SettingsPage() {
  const { t } = useTranslation();
  const preferences = usePreferences();
  const update = useUpdatePreferences();
  // What was just picked shows at once, while it is saved; a failed save falls back to what is
  // stored.
  const shown = update.isPending ? update.variables : preferences.data;
  // Each change goes on top of the one before it, saved or not yet: building it on what the
  // server last answered would undo a change still on its way.
  const latest = useRef<Preferences | null>(null);
  const save: Save = (change) => {
    const base = latest.current ?? preferences.data;
    if (!base) return;
    latest.current = { ...base, ...change };
    update.mutate(latest.current, {
      onError: () => {
        latest.current = null;
      },
    });
  };

  return (
    <section className="grid gap-4">
      <h1 className="font-display text-2xl font-semibold tracking-tight">{t("settings.title")}</h1>
      <p className="max-w-prose text-muted">{t("settings.intro")}</p>
      {preferences.isPending && <p className="text-muted">{t("settings.loading")}</p>}
      {preferences.isError && (
        <p role="alert" className="text-crit">
          {t("settings.error")}
        </p>
      )}
      <div aria-live="polite" className="min-h-6 text-sm">
        {update.isSuccess && <p role="status">{t("settings.saved")}</p>}
        {update.isError && (
          <p role="alert" className="text-crit">
            {t("settings.saveError")}
          </p>
        )}
      </div>
      {shown && (
        <PageGrid columns={2}>
          <StockSettings shown={shown} save={save} />
          <CodeSettings shown={shown} save={save} />
          <FormatSettings shown={shown} save={save} />
          <TrashSettings shown={shown} save={save} />
        </PageGrid>
      )}
    </section>
  );
}

type SectionProps = { shown: Preferences; save: Save };

function StockSettings({ shown, save }: SectionProps) {
  const { t } = useTranslation();
  return (
    <Block title={t("settings.stock.title")}>
      <Choice
        legend={t("settings.stock.basis.legend")}
        hint={t("settings.stock.basis.hint")}
        name="stock-basis"
        options={BASES}
        value={shown.stock_basis}
        label={(basis) => t(`settings.stock.basis.${basis}.label`)}
        detail={(basis) => t(`settings.stock.basis.${basis}.detail`)}
        onChange={(stock_basis) => save({ stock_basis })}
      />
      <TypedSetting
        // Remounted when the stored answer changes, so the field shows what is kept.
        key={`minimum:${shown.default_minimum_stock}`}
        label={t("settings.stock.defaultMinimum.label")}
        hint={t("settings.stock.defaultMinimum.hint")}
        stored={shown.default_minimum_stock === null ? "" : String(shown.default_minimum_stock)}
        inputMode="numeric"
        invalid={(typed) =>
          typed !== "" && !(/^\d{1,7}$/.test(typed) && Number(typed) <= MAX_MINIMUM_STOCK)
        }
        invalidText={t("settings.stock.defaultMinimum.invalid")}
        onSave={(typed) => save({ default_minimum_stock: typed === "" ? null : Number(typed) })}
      />
    </Block>
  );
}

function CodeSettings({ shown, save }: SectionProps) {
  const { t } = useTranslation();
  return (
    <Block title={t("settings.codes.title")}>
      <TypedSetting
        key={`prefix:${shown.code_prefix}`}
        label={t("settings.codes.prefix.label")}
        hint={t("settings.codes.prefix.hint", {
          location: `${shown.code_prefix}-L-0007`,
          unit: `${shown.code_prefix}-U-0042`,
        })}
        stored={shown.code_prefix}
        transform={(typed) => typed.toUpperCase()}
        invalid={(typed) => !PREFIX.test(typed)}
        invalidText={t("settings.codes.prefix.invalid")}
        onSave={(typed) => save({ code_prefix: typed.toUpperCase() })}
      />
      <p className="text-sm text-muted">
        {t("settings.codes.kept")}{" "}
        <Link to="/locations" className="font-semibold text-primary hover:underline">
          {t("settings.codes.locations")}
        </Link>
      </p>
    </Block>
  );
}

function FormatSettings({ shown, save }: SectionProps) {
  const { t, i18n } = useTranslation();
  const example = (date: Preferences["date_format"], number: Preferences["number_format"]) =>
    formatsOf(i18n.language, date, number);
  return (
    <Block title={t("settings.formats.title")}>
      <Choice
        legend={t("settings.formats.date.legend")}
        name="date-format"
        options={DATE_FORMATS}
        value={shown.date_format}
        label={(format) => t(`settings.formats.date.${format}`)}
        detail={(format) => example(format, shown.number_format).dateTime(EXAMPLE_DATE)}
        onChange={(date_format) => save({ date_format })}
      />
      <Choice
        legend={t("settings.formats.number.legend")}
        name="number-format"
        options={NUMBER_FORMATS}
        value={shown.number_format}
        label={(format) => t(`settings.formats.number.${format}`)}
        detail={(format) =>
          example(shown.date_format, format).number(EXAMPLE_NUMBER, { minimumFractionDigits: 1 })
        }
        onChange={(number_format) => save({ number_format })}
      />
    </Block>
  );
}

function TrashSettings({ shown, save }: SectionProps) {
  const { t } = useTranslation();
  const id = useId();
  const kept = shown.trash_retention_days;
  // A number saved some other way still shows, as itself.
  const options: readonly (number | null)[] =
    kept === null || (RETENTIONS as readonly (number | null)[]).includes(kept)
      ? RETENTIONS
      : [...RETENTIONS, kept];
  return (
    <Block title={t("settings.trash.title")}>
      <div className="grid gap-1">
        <label htmlFor={id} className="font-medium">
          {t("settings.trash.label")}
        </label>
        <select
          id={id}
          value={kept === null ? "" : String(kept)}
          aria-describedby={`${id}-hint`}
          onChange={(event) =>
            save({
              trash_retention_days: event.target.value === "" ? null : Number(event.target.value),
            })
          }
          className={`${control} max-w-xs`}
        >
          {options.map((days) => (
            <option key={days ?? "forever"} value={days === null ? "" : String(days)}>
              {days === null
                ? t("settings.trash.forever")
                : t("settings.trash.days", { count: days })}
            </option>
          ))}
        </select>
        <p id={`${id}-hint`} className="text-sm text-muted">
          {kept === null
            ? t("settings.trash.hintForever")
            : t("settings.trash.hint", { count: kept })}
        </p>
      </div>
    </Block>
  );
}

type ChoiceProps<T extends string> = {
  legend: string;
  hint?: string;
  name: string;
  options: readonly T[];
  value: T;
  label: (option: T) => string;
  detail: (option: T) => ReactNode;
  onChange: (option: T) => void;
};

/** One choice among a few, each with what it means beside it. */
function Choice<T extends string>({
  legend,
  hint,
  name,
  options,
  value,
  label,
  detail,
  onChange,
}: ChoiceProps<T>) {
  const hintId = useId();
  return (
    <fieldset className="grid gap-3" aria-describedby={hint ? hintId : undefined}>
      <legend className="font-medium">{legend}</legend>
      {hint && (
        <p id={hintId} className="text-sm text-muted">
          {hint}
        </p>
      )}
      {options.map((option) => (
        <label key={option} className="flex items-start gap-3">
          <input
            type="radio"
            name={name}
            value={option}
            checked={value === option}
            onChange={() => onChange(option)}
            className="mt-1"
          />
          <span className="grid">
            <span className="font-medium">{label(option)}</span>
            <span className="text-sm text-muted">{detail(option)}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

type TypedProps = {
  label: string;
  hint: string;
  stored: string;
  inputMode?: "numeric";
  transform?: (typed: string) => string;
  invalid: (typed: string) => boolean;
  invalidText: string;
  onSave: (typed: string) => void;
};

/**
 * A setting typed in a field: saved when the field is left or Enter is pressed, only when it
 * changed and only when it is valid; what is wrong is said under it, in place of the hint.
 */
function TypedSetting({
  label,
  hint,
  stored,
  inputMode,
  transform,
  invalid,
  invalidText,
  onSave,
}: TypedProps) {
  const id = useId();
  const [typed, setTyped] = useState(stored);
  const value = typed.trim();
  const wrong = invalid(value);

  function save() {
    if (!wrong && value !== stored) onSave(value);
  }

  return (
    <div className="grid gap-1">
      <label htmlFor={id} className="font-medium">
        {label}
      </label>
      <input
        id={id}
        type="text"
        inputMode={inputMode}
        value={typed}
        aria-invalid={wrong ? true : undefined}
        aria-describedby={`${id}-hint`}
        onChange={(event) =>
          setTyped(transform ? transform(event.target.value) : event.target.value)
        }
        onBlur={save}
        onKeyDown={(event) => {
          if (event.key === "Enter") save();
        }}
        className={`${control} max-w-40 font-mono`}
      />
      <p id={`${id}-hint`} className={`text-sm ${wrong ? "text-crit" : "text-muted"}`}>
        {wrong ? invalidText : hint}
      </p>
    </div>
  );
}
