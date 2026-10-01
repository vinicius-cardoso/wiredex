import { zodResolver } from "@hookform/resolvers/zod";
import type {
  FirmwareChange,
  FirmwareDetails,
  FirmwareField,
  Framework,
} from "@wiredex/api-client";
import type { TFunction } from "i18next";
import { useId, useMemo } from "react";
import { type UseFormReturn, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { FirmwareRefusal, useCreateFirmware, useUpdateFirmware } from "./firmware";
import { FRAMEWORKS, frameworkKey } from "./labels";

/** The server's caps (requirements 1.2, 1.4, 1.6), checked here so the form says so first. */
const MAX_NAME_LENGTH = 120;
const MAX_TARGET_LENGTH = 200;
const MAX_DESCRIPTION_LENGTH = 4_000;

const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";

type FirmwareFormValues = {
  name: string;
  target: string;
  framework: Framework;
  description: string;
};

/** The fields this form shows a refusal on; the API's other fields belong to versions. */
type FormField = Extract<FirmwareField, "name" | "target" | "description">;

type Props = {
  /** The firmware being edited; absent, the form creates one. */
  firmware?: FirmwareDetails;
  /** The revision a new firmware runs on from the start (requirement 3.3). */
  revisionId?: string | undefined;
  onSaved: (firmware: FirmwareDetails) => void;
  onCancel?: () => void;
};

/**
 * A firmware's name, board target, framework and description, for a new firmware and an edit.
 * The Zod schema mirrors the server's value rules, so a blank or over-long name or target is
 * caught before a request goes out; the API checks again regardless, and its refusal lands on
 * the field it names, in the reader's language (requirement 1.3).
 */
export function FirmwareForm({ firmware, revisionId, onSaved, onCancel }: Props) {
  const { t } = useTranslation();
  const create = useCreateFirmware();
  const update = useUpdateFirmware();
  const saving = create.isPending || update.isPending;
  const resolver = useMemo(() => zodResolver(firmwareSchema(t)), [t]);
  const form = useForm<FirmwareFormValues>({
    defaultValues: {
      name: firmware?.name ?? "",
      target: firmware?.target ?? "",
      framework: firmware?.framework ?? "arduino",
      description: firmware?.description ?? "",
    },
    resolver,
  });
  const ids = { name: useId(), target: useId(), framework: useId(), description: useId() };

  const errors = form.formState.errors;
  const rootError = errors.root?.message;

  function save(values: FirmwareFormValues) {
    const callbacks = {
      onSuccess: onSaved,
      onError: (error: unknown) => showRefusal(error, form, t, firmware ? "firmware" : "revision"),
    };
    // An edit replaces all four (requirement 1.7): the whole form goes, as a create's does.
    if (firmware) {
      update.mutate({ firmwareId: firmware.id, body: requestFrom(values) }, callbacks);
    } else {
      create.mutate({ ...requestFrom(values), revision_id: revisionId ?? null }, callbacks);
    }
  }

  /** The error under a field, tied to it so a screen reader reads it with the field. */
  function described(field: FormField) {
    const error = errors[field];
    return {
      "aria-invalid": error ? true : undefined,
      ...(error ? { "aria-describedby": `${ids[field]}-error` } : {}),
    };
  }

  function problem(field: FormField) {
    const error = errors[field];
    return error ? (
      <p id={`${ids[field]}-error`} className="text-sm text-crit">
        {error.message}
      </p>
    ) : null;
  }

  return (
    <form
      // Kept off the browser's own validation: the messages here are translated and shown
      // where the field is, which native bubbles can't do.
      noValidate
      onSubmit={(event) => void form.handleSubmit(save)(event)}
      className="grid max-w-2xl gap-4"
    >
      <div className="grid gap-1">
        <label htmlFor={ids.name} className="text-sm font-medium">
          {t("firmware.form.name")}
        </label>
        <input
          id={ids.name}
          type="text"
          className={control}
          aria-required={true}
          {...described("name")}
          {...form.register("name")}
        />
        {problem("name")}
      </div>

      <div className="grid gap-1">
        <label htmlFor={ids.target} className="text-sm font-medium">
          {t("firmware.form.target")}
        </label>
        <input
          id={ids.target}
          type="text"
          // An FQBN is typed as its toolchain spells it, so nothing may change its case.
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          placeholder={t("firmware.form.targetPlaceholder")}
          className={`${control} font-mono`}
          aria-required={true}
          {...described("target")}
          {...form.register("target")}
        />
        {problem("target")}
      </div>

      <div className="grid gap-1">
        <label htmlFor={ids.framework} className="text-sm font-medium">
          {t("firmware.form.framework")}
        </label>
        <select id={ids.framework} className={control} {...form.register("framework")}>
          {FRAMEWORKS.map((framework) => (
            <option key={framework} value={framework}>
              {t(frameworkKey(framework))}
            </option>
          ))}
        </select>
      </div>

      <div className="grid gap-1">
        <label htmlFor={ids.description} className="text-sm font-medium">
          {t("firmware.form.description")}
        </label>
        <textarea
          id={ids.description}
          rows={4}
          className={control}
          {...described("description")}
          {...form.register("description")}
        />
        {problem("description")}
      </div>

      {rootError && (
        <p role="alert" className="rounded-md border border-crit px-3 py-2 text-sm text-crit">
          {rootError}
        </p>
      )}

      <div className="flex flex-wrap gap-3">
        <button
          type="submit"
          disabled={saving}
          className="rounded-md bg-primary px-4 py-2 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {saving ? t("firmware.form.saving") : t("firmware.form.save")}
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
          >
            {t("firmware.form.cancel")}
          </button>
        )}
      </div>
    </form>
  );
}

/** Whitespace collapsed, as the server reads a name and a target (requirements 1.2, 1.4). */
function collapsed(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ");
}

/** Line breaks unified and ends trimmed, as the server reads a description (1.6). */
function plain(text: string): string {
  return text.replace(/\r\n?/g, "\n").trim();
}

function firmwareSchema(t: TFunction) {
  const required = (message: string, max: number) =>
    z.string().superRefine((value, ctx) => {
      const text = collapsed(value);
      if (text === "") ctx.addIssue(message);
      else if ([...text].length > max) ctx.addIssue(t("firmware.form.error.tooLong", { max }));
    });
  return z.object({
    name: required(t("firmware.form.error.nameRequired"), MAX_NAME_LENGTH),
    target: required(t("firmware.form.error.targetRequired"), MAX_TARGET_LENGTH),
    framework: z.enum(FRAMEWORKS),
    description: z.string().superRefine((value, ctx) => {
      if ([...plain(value)].length > MAX_DESCRIPTION_LENGTH) {
        ctx.addIssue(t("firmware.form.error.tooLong", { max: MAX_DESCRIPTION_LENGTH }));
      }
    }),
  });
}

function requestFrom(values: FirmwareFormValues): FirmwareChange {
  const description = plain(values.description);
  return {
    name: collapsed(values.name),
    target: collapsed(values.target),
    framework: values.framework,
    // A cleared description is none, never a refusal (requirement 1.6).
    description: description === "" ? null : description,
  };
}

function formField(field: FirmwareField | null): FormField | null {
  return field === "name" || field === "target" || field === "description" ? field : null;
}

/**
 * A refusal, shown where it belongs: on the field it names, from its code, so a name another
 * firmware holds is marked on the name (requirement 1.3). A 404 is what the write named and
 * the workspace no longer holds: the firmware an edit changes, or the revision a new one is
 * for (3.7). Anything else is the form's problem.
 */
function showRefusal(
  error: unknown,
  form: UseFormReturn<FirmwareFormValues>,
  t: TFunction,
  gone: "firmware" | "revision",
) {
  const refusal = error instanceof FirmwareRefusal ? error : null;
  const field = formField(refusal?.field ?? null);
  if (refusal && field) {
    const message =
      refusal.code === "name_taken"
        ? t("firmware.refusal.name_taken", { item: refusal.item ?? "" })
        : t(`firmware.refusal.invalid_${field}`);
    form.setError(field, { type: "server", message });
  } else {
    const missing =
      gone === "firmware" ? "firmware.form.error.firmwareGone" : "firmware.form.error.revisionGone";
    const key = refusal?.status === 404 ? missing : "firmware.form.error.save";
    form.setError("root", { type: "server", message: t(key) });
  }
}
