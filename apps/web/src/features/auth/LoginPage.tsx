import { getRouteApi, useNavigate } from "@tanstack/react-router";
import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { loginFailure, useLogIn } from "./auth";

const route = getRouteApi("/login");

const field = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";

export function LoginPage() {
  const { t } = useTranslation();
  const { redirect } = route.useSearch();
  const navigate = useNavigate();
  const logIn = useLogIn();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const credentials = {
      email: String(form.get("email")),
      password: String(form.get("password")),
    };
    logIn.mutate(credentials, { onSuccess: () => navigate({ href: redirect ?? "/" }) });
  }

  return (
    <section className="mx-auto grid w-full max-w-sm gap-6 pt-8">
      <h1 className="font-display text-3xl font-semibold tracking-tight">{t("login.title")}</h1>
      <form onSubmit={submit} className="grid gap-4">
        <label className="grid gap-1 text-sm font-medium">
          {t("login.email")}
          <input name="email" type="email" autoComplete="username" required className={field} />
        </label>
        <label className="grid gap-1 text-sm font-medium">
          {t("login.password")}
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
            className={field}
          />
        </label>
        {logIn.isError && (
          <p role="alert" className="rounded-md border border-crit px-3 py-2 text-sm text-crit">
            {t(`login.error.${loginFailure(logIn.error)}`)}
          </p>
        )}
        <button
          type="submit"
          disabled={logIn.isPending}
          className="rounded-md bg-primary px-4 py-2 font-semibold text-on-primary hover:opacity-90 disabled:opacity-60"
        >
          {logIn.isPending ? t("login.submitting") : t("login.submit")}
        </button>
      </form>
      <p className="text-sm text-muted">{t("login.noSignup")}</p>
    </section>
  );
}
