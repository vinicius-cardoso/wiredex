import { useTranslation } from "react-i18next";
import { useRecentActivity, useShortRevisions, useTiedUpParts } from "./dashboard";
import { RecentActivityPanel } from "./RecentActivity";
import { ShortagesPanel } from "./Shortages";
import { TiedUpPartsPanel } from "./TiedUpParts";

/**
 * The page the app opens on (18-dashboard): what the builds hold, what the next builds are
 * missing, and what changed last, each panel its own read, so a slow one never holds the others
 * back (decision 1). A bench with nothing in any of them keeps the invitation a new bench gets
 * (requirement 5.2).
 */
export function DashboardPage() {
  const { t } = useTranslation();
  const tiedUp = useTiedUpParts();
  const shortages = useShortRevisions();
  const activity = useRecentActivity();
  const empty =
    tiedUp.data?.parts.length === 0 &&
    shortages.data?.revisions.length === 0 &&
    activity.data?.changes.length === 0;

  return (
    <section className="grid gap-4">
      <h1 className="font-display text-2xl font-semibold tracking-tight">{t("dashboard.title")}</h1>
      {empty ? (
        <p className="max-w-prose rounded-lg border border-dashed border-border-strong bg-surface p-6 text-muted">
          {t("dashboard.empty")}
        </p>
      ) : (
        // Side by side on a laptop, so the three read at a glance; the third drops under the
        // first two on a narrower screen.
        <div className="grid min-w-0 gap-4 lg:grid-cols-2 xl:grid-cols-3">
          <TiedUpPartsPanel query={tiedUp} />
          <ShortagesPanel query={shortages} />
          <div className="min-w-0 lg:col-span-2 xl:col-span-1">
            <RecentActivityPanel query={activity} />
          </div>
        </div>
      )}
    </section>
  );
}
