import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

export function NotFoundPage() {
  const { t } = useTranslation();

  return (
    <section className="grid gap-4">
      <h1 className="font-display text-3xl font-semibold">{t("notFound.title")}</h1>
      <Link to="/" className="text-primary underline underline-offset-4">
        {t("notFound.back")}
      </Link>
    </section>
  );
}
