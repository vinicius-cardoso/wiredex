import { useState } from "react";
import { useTranslation } from "react-i18next";
import { LocationPicker } from "../../inventory/LocationPicker";
import { control, dialogPrimary, StockDialog } from "../../inventory/StockDialog";
import { LifecycleRefusal, useDismantleRevision } from "./lifecycle";
import { refusalMessage } from "./refusal";

type Props = { revisionId: string; onClose: () => void };

/**
 * *Dismantle* asks for the location everything the build used returns to, with 07's location
 * picker (requirement 13.5). The send stays disabled until a location is picked; an
 * `unknown_location` shows in the dialog, in the reader's language (requirements 13.5, 13.13).
 */
export function DismantleDialog({ revisionId, onClose }: Props) {
  const { t } = useTranslation();
  const dismantle = useDismantleRevision();
  const [locationId, setLocationId] = useState<string | null>(null);

  const refusal = dismantle.error instanceof LifecycleRefusal ? dismantle.error : null;

  function send() {
    if (!locationId) return;
    dismantle.mutate({ revisionId, locationId }, { onSuccess: onClose });
  }

  return (
    <StockDialog title={t("projects.lifecycle.dismantle.title")} onClose={onClose}>
      <div className="grid gap-3">
        <p className="text-sm text-muted">{t("projects.lifecycle.dismantle.explain")}</p>
        <LocationPicker
          label={t("projects.lifecycle.dismantle.location")}
          value={locationId}
          onChange={setLocationId}
          invalid={refusal?.code === "unknown_location"}
        />
        {dismantle.isError && (
          <p role="alert" className="text-sm text-crit">
            {refusalMessage(t, refusal)}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!locationId || dismantle.isPending}
            onClick={send}
            className={dialogPrimary}
          >
            {t("projects.lifecycle.dismantle.confirm")}
          </button>
          <button type="button" onClick={onClose} className={control}>
            {t("projects.lifecycle.dismantle.cancel")}
          </button>
        </div>
      </div>
    </StockDialog>
  );
}
