import { type ErrorComponentProps, useRouter } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

/** Shown when a page can't load, e.g. the API is down or restarting during a deploy. */
export function ErrorPage({ reset }: ErrorComponentProps) {
  const { t } = useTranslation();
  const router = useRouter();

  async function retry() {
    await router.invalidate();
    reset();
  }

  return (
    <section className="grid max-w-prose gap-4">
      <h1 className="font-display text-3xl font-semibold">{t("error.title")}</h1>
      <p className="text-muted">{t("error.body")}</p>
      <button
        type="button"
        onClick={retry}
        className="justify-self-start rounded-md bg-primary px-4 py-2 font-semibold text-on-primary hover:opacity-90"
      >
        {t("error.retry")}
      </button>
    </section>
  );
}
