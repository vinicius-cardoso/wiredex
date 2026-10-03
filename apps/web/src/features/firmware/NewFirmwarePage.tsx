import { getRouteApi, Link, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { useRevisionRef } from "../projects/build/lifecycle";
import { RevisionRefLink } from "../projects/build/RevisionLink";
import { FirmwareForm } from "./FirmwareForm";

const route = getRouteApi("/authenticated/firmware/new");

/**
 * The page behind `/firmware/new`, then the new firmware's own page (requirement 11.3). With
 * `?revision=` it is started from that revision: the page names the revision before anything
 * is saved, and the firmware is created running on it in the same write (11.4, 3.3).
 */
export function NewFirmwarePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { revision } = route.useSearch();

  return (
    <section className="grid gap-4">
      <h1 className="font-display text-2xl font-semibold tracking-tight">
        {t("firmware.form.newTitle")}
      </h1>
      {revision && <ForRevision revisionId={revision} />}
      <FirmwareForm
        revisionId={revision}
        onSaved={(firmware) =>
          void navigate({ to: "/firmware/$firmwareId", params: { firmwareId: firmware.id } })
        }
        onCancel={() => void navigate({ to: "/firmware" })}
      />
    </section>
  );
}

/**
 * Which revision the new firmware will run on, by its project and label, through 10's link. A
 * revision the workspace doesn't hold says so before the save would be refused with a 404.
 */
function ForRevision({ revisionId }: { revisionId: string }) {
  const { t } = useTranslation();
  const ref = useRevisionRef(revisionId);

  if (ref.isError) {
    return (
      <div role="alert" className="grid justify-items-start gap-1 text-crit">
        <p>{t("firmware.form.noSuchRevision")}</p>
        <Link to="/firmware/new" className="font-semibold text-primary hover:underline">
          {t("firmware.form.withoutRevision")}
        </Link>
      </div>
    );
  }
  if (!ref.data) return <p className="text-muted">{t("firmware.form.loadingRevision")}</p>;
  return (
    <p>
      {t("firmware.form.forRevision")} <RevisionRefLink revision={ref.data} />
    </p>
  );
}
