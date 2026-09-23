import { useTranslation } from "react-i18next";

export function DashboardPage() {
  const { t } = useTranslation();

  return (
    <section className="grid gap-4">
      <h1 className="font-display text-3xl font-semibold tracking-tight">{t("dashboard.title")}</h1>
      <p className="max-w-prose rounded-lg border border-dashed border-border-strong bg-surface p-6 text-muted">
        {t("dashboard.empty")}
      </p>
    </section>
  );
}
