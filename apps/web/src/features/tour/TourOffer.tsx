import { useTranslation } from "react-i18next";
import { useTour } from "./TourProvider";

/**
 * The dashboard's offer of the tour, until it is answered either way on this device. Never
 * forced: *Not now* puts it away, and the account menu keeps the tour for later.
 */
export function TourOffer() {
  const { t } = useTranslation();
  const tour = useTour();
  if (!tour.offering) return null;

  return (
    <section
      aria-label={t("tour.offer.label")}
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-primary bg-surface px-4 py-3"
    >
      <p className="min-w-0 text-sm">
        <span className="font-semibold">{t("tour.offer.title")}</span>{" "}
        <span className="text-muted">{t("tour.offer.text")}</span>
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={tour.start}
          className="rounded-md bg-primary px-3 py-1 text-sm font-semibold text-on-primary hover:opacity-90"
        >
          {t("tour.take")}
        </button>
        <button
          type="button"
          onClick={tour.decline}
          className="rounded-md border border-border-strong px-3 py-1 text-sm hover:bg-surface-2"
        >
          {t("tour.offer.notNow")}
        </button>
      </div>
    </section>
  );
}
