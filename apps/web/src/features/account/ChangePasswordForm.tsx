import { type FormEvent, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCurrentUser } from "../auth/auth";
import { type PasswordFailure, passwordFailure, useChangePassword } from "./password";

/** The server's floor (ADR 0008), checked here so the form says so before a request goes. */
const MIN_PASSWORD_LENGTH = 12;

const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";

type Problem = { field: "current" | "new" | "confirm" | null; message: string };

/** Which field each refusal belongs under; the rest are the form's. */
const FIELD_OF: Partial<Record<PasswordFailure, "current" | "new">> = {
  wrong_password: "current",
  weak_password: "new",
  same_password: "new",
  password_like_account: "new",
};

/**
 * Changing your own password (spec 23). It asks for the current one again, so someone at an
 * unlocked screen can't change it, and for the new one twice, since it can't be read back.
 *
 * The three fields are never held in React state: they are read from the form when it is
 * sent and the form is cleared when the answer comes, whatever it was, so no password lingers
 * in memory or in a devtools snapshot. The hidden email lets a password manager file the new
 * password under the right account.
 */
export function ChangePasswordForm() {
  const { t } = useTranslation();
  const user = useCurrentUser();
  const change = useChangePassword();
  const form = useRef<HTMLFormElement>(null);
  const [shown, setShown] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [done, setDone] = useState<number | null>(null);
  const ids = {
    title: useId(),
    current: useId(),
    new: useId(),
    confirm: useId(),
    hint: useId(),
    error: useId(),
  };

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const [current, next, confirm] = ["current", "new", "confirm"].map((name) =>
      String(fields.get(name) ?? ""),
    ) as [string, string, string];
    setDone(null);
    const refused = check(current, next, confirm);
    if (refused) {
      setProblem({ field: refused.field, message: t(`account.password.error.${refused.key}`) });
      return;
    }
    setProblem(null);
    change.mutate(
      { currentPassword: current, newPassword: next },
      {
        onSuccess: (revoked) => {
          form.current?.reset();
          setDone(revoked);
        },
        onError: (error) => {
          const failure = passwordFailure(error);
          // A wrong current password is typed again; the new one is kept to fix or resend.
          if (failure === "wrong_password" || failure === "throttled") clear("current");
          setProblem({
            field: FIELD_OF[failure] ?? null,
            message: t(`account.password.error.${failure}`),
          });
        },
      },
    );
  }

  function clear(name: string) {
    const input = form.current?.elements.namedItem(name);
    if (input instanceof HTMLInputElement) {
      input.value = "";
      input.focus();
    }
  }

  const type = shown ? "text" : "password";
  const marked = (field: Problem["field"]) =>
    problem?.field === field
      ? { "aria-invalid": true as const, "aria-describedby": ids.error }
      : {};

  return (
    <form
      ref={form}
      onSubmit={submit}
      noValidate
      aria-labelledby={ids.title}
      className="mt-4 grid max-w-md gap-4"
    >
      <h2 id={ids.title} className="font-display text-xl font-semibold tracking-tight">
        {t("account.password.title")}
      </h2>
      {/* Not shown: what a password manager reads to know whose password this is. */}
      <input
        type="email"
        name="username"
        autoComplete="username"
        value={user.data?.email ?? ""}
        readOnly
        hidden
      />
      <div className="grid gap-1">
        <label htmlFor={ids.current} className="text-sm font-medium">
          {t("account.password.current")}
        </label>
        <input
          id={ids.current}
          name="current"
          type={type}
          autoComplete="current-password"
          aria-required={true}
          className={control}
          {...marked("current")}
        />
      </div>
      <div className="grid gap-1">
        <label htmlFor={ids.new} className="text-sm font-medium">
          {t("account.password.new")}
        </label>
        <input
          id={ids.new}
          name="new"
          type={type}
          autoComplete="new-password"
          aria-required={true}
          aria-describedby={problem?.field === "new" ? ids.error : ids.hint}
          aria-invalid={problem?.field === "new" ? true : undefined}
          className={control}
        />
        <p id={ids.hint} className="text-sm text-muted">
          {t("account.password.hint", { min: MIN_PASSWORD_LENGTH })}
        </p>
      </div>
      <div className="grid gap-1">
        <label htmlFor={ids.confirm} className="text-sm font-medium">
          {t("account.password.confirm")}
        </label>
        <input
          id={ids.confirm}
          name="confirm"
          type={type}
          autoComplete="new-password"
          aria-required={true}
          className={control}
          {...marked("confirm")}
        />
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={shown} onChange={() => setShown((now) => !now)} />
        {t("account.password.show")}
      </label>

      {problem && (
        <p
          id={ids.error}
          role="alert"
          className="rounded-md border border-crit px-3 py-2 text-sm text-crit"
        >
          {problem.message}
        </p>
      )}
      {done !== null && (
        <p role="status" className="rounded-md border border-ok px-3 py-2 text-sm">
          {t("account.password.done")}{" "}
          {done === 0
            ? t("account.password.noneRevoked")
            : t("account.password.revoked", { count: done })}
        </p>
      )}

      <div>
        <button
          type="submit"
          disabled={change.isPending}
          className="rounded-md bg-primary px-4 py-2 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {t(change.isPending ? "account.password.saving" : "account.password.save")}
        </button>
      </div>
      <p className="text-sm text-muted">{t("account.password.after")}</p>
    </form>
  );
}

type LocalProblem = "currentRequired" | "weak_password" | "same_password" | "mismatch";

/** What the form can tell is wrong without asking; the API decides the rest. */
function check(
  current: string,
  next: string,
  confirm: string,
): { field: "current" | "new" | "confirm"; key: LocalProblem } | null {
  if (current === "") return { field: "current", key: "currentRequired" };
  if ([...next].length < MIN_PASSWORD_LENGTH) return { field: "new", key: "weak_password" };
  if (next === current) return { field: "new", key: "same_password" };
  if (confirm !== next) return { field: "confirm", key: "mismatch" };
  return null;
}
