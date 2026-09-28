import { zodResolver } from "@hookform/resolvers/zod";
import { useNavigate } from "@tanstack/react-router";
import type { NewProject, ProjectDetails } from "@wiredex/api-client";
import type { TFunction } from "i18next";
import { useId, useMemo } from "react";
import { Controller, type UseFormReturn, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { ProjectRefusal, useCreateProject, useProjectTags, useUpdateProject } from "./projects";
import { MAX_TAGS, TagInput } from "./TagInput";

/** The server's caps (requirements 1.2, 1.4), checked here so the form says so first. */
const MAX_NAME_LENGTH = 120;
const MAX_DESCRIPTION_LENGTH = 4_000;

const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";

type ProjectFormValues = { name: string; description: string; tags: string[] };

type Props = {
  /** The project being edited; absent, the form creates one. */
  project?: ProjectDetails;
  onSaved: (project: ProjectDetails) => void;
  onCancel?: () => void;
};

/**
 * A project's name, description and tags. The Zod schema mirrors the server's value rules,
 * so a blank or over-long name is caught before a request goes out; the API checks again
 * regardless, and a name another project holds (409) lands on the name (requirement 1.3).
 */
export function ProjectForm({ project, onSaved, onCancel }: Props) {
  const { t } = useTranslation();
  const create = useCreateProject();
  const update = useUpdateProject();
  const saving = create.isPending || update.isPending;
  const tags = useProjectTags();
  const resolver = useMemo(() => zodResolver(projectSchema(t)), [t]);
  const form = useForm<ProjectFormValues>({
    defaultValues: {
      name: project?.name ?? "",
      description: project?.description ?? "",
      tags: project?.tags ?? [],
    },
    resolver,
  });
  const nameId = useId();
  const descriptionId = useId();
  const tagsErrorId = useId();

  const errors = form.formState.errors;
  const rootError = errors.root?.message;
  const tagsError = errors.tags?.message;
  const suggestions = (tags.data ?? []).map((held) => held.tag);

  function save(values: ProjectFormValues) {
    const callbacks = {
      onSuccess: onSaved,
      onError: (error: unknown) => showRefusal(error, form, t),
    };
    // An edit replaces what it names (requirement 1.5): the whole form goes, as a create's does.
    if (project) update.mutate({ projectId: project.id, body: requestFrom(values) }, callbacks);
    else create.mutate(requestFrom(values), callbacks);
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
        <label htmlFor={nameId} className="text-sm font-medium">
          {t("projects.form.name")}
        </label>
        <input
          id={nameId}
          type="text"
          className={control}
          aria-required={true}
          aria-invalid={errors.name ? true : undefined}
          {...(errors.name ? { "aria-describedby": `${nameId}-error` } : {})}
          {...form.register("name")}
        />
        {errors.name && (
          <p id={`${nameId}-error`} className="text-sm text-crit">
            {errors.name.message}
          </p>
        )}
      </div>

      <div className="grid gap-1">
        <label htmlFor={descriptionId} className="text-sm font-medium">
          {t("projects.form.description")}
        </label>
        <textarea
          id={descriptionId}
          rows={5}
          className={control}
          aria-invalid={errors.description ? true : undefined}
          {...(errors.description ? { "aria-describedby": `${descriptionId}-error` } : {})}
          {...form.register("description")}
        />
        {errors.description && (
          <p id={`${descriptionId}-error`} className="text-sm text-crit">
            {errors.description.message}
          </p>
        )}
      </div>

      <Controller
        control={form.control}
        name="tags"
        render={({ field }) => (
          <TagInput
            label={t("projects.form.tags")}
            value={field.value}
            onChange={field.onChange}
            suggestions={suggestions}
            invalid={Boolean(tagsError)}
            {...(tagsError ? { describedBy: tagsErrorId } : {})}
          />
        )}
      />
      {tagsError && (
        <p id={tagsErrorId} className="text-sm text-crit">
          {tagsError}
        </p>
      )}

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
          {saving ? t("projects.form.saving") : t("projects.form.save")}
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2"
          >
            {t("projects.form.cancel")}
          </button>
        )}
      </div>
    </form>
  );
}

/** The page behind `/projects/new`: the form, then the new project on its revision A. */
export function NewProjectPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <section className="grid gap-4">
      <h1 className="font-display text-3xl font-semibold tracking-tight">
        {t("projects.form.newTitle")}
      </h1>
      <ProjectForm
        onSaved={(project) =>
          void navigate({ to: "/projects/$projectId", params: { projectId: project.id } })
        }
        onCancel={() => void navigate({ to: "/projects" })}
      />
    </section>
  );
}

/** Whitespace collapsed, as the server reads a name (requirement 1.2). */
function collapsed(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ");
}

/** Line breaks unified and ends trimmed, as the server reads a description (1.4). */
function plain(text: string): string {
  return text.replace(/\r\n?/g, "\n").trim();
}

function projectSchema(t: TFunction) {
  return z.object({
    name: z.string().superRefine((value, ctx) => {
      const name = collapsed(value);
      if (name === "") ctx.addIssue(t("projects.form.error.nameRequired"));
      else if ([...name].length > MAX_NAME_LENGTH) {
        ctx.addIssue(t("projects.form.error.tooLong", { max: MAX_NAME_LENGTH }));
      }
    }),
    description: z.string().superRefine((value, ctx) => {
      if ([...plain(value)].length > MAX_DESCRIPTION_LENGTH) {
        ctx.addIssue(t("projects.form.error.tooLong", { max: MAX_DESCRIPTION_LENGTH }));
      }
    }),
    tags: z.array(z.string()).max(MAX_TAGS, t("projects.tags.error.tooMany", { max: MAX_TAGS })),
  });
}

function requestFrom(values: ProjectFormValues): NewProject {
  const description = plain(values.description);
  return {
    name: collapsed(values.name),
    description: description === "" ? null : description,
    tags: values.tags,
  };
}

/**
 * A refusal, shown where it belongs: a 409 is always the name another project holds, a 422
 * names the field it is about, and anything else is the form's problem.
 */
function showRefusal(error: unknown, form: UseFormReturn<ProjectFormValues>, t: TFunction) {
  const refusal = error instanceof ProjectRefusal ? error : null;
  const detail = refusal?.detail ?? "";
  const message = { type: "server", message: detail };
  if (refusal?.status === 409) form.setError("name", message);
  else if (refusal?.status === 422 && /\btags?\b/i.test(detail)) form.setError("tags", message);
  else if (refusal?.status === 422 && /\bname\b/i.test(detail)) form.setError("name", message);
  else if (refusal?.status === 422 && /description/i.test(detail)) {
    form.setError("description", message);
  } else
    form.setError("root", { type: "server", message: detail || t("projects.form.error.save") });
}
