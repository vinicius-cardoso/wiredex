import type { Preferences } from "@wiredex/api-client";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { Block } from "../../shared/ui/block";
import { usePreferences, useUpdatePreferences } from "./preferences";

const BASES = ["free", "total"] as const satisfies readonly Preferences["stock_basis"][];

/**
 * The workspace's settings (spec 24): the choices that change what its pages answer, kept on
 * the server so every device agrees. Each is saved as it is picked, and says so.
 */
export function SettingsPage() {
  const { t } = useTranslation();
  const preferences = usePreferences();
  const update = useUpdatePreferences();
  const hintId = useId();
  // What was just picked shows at once, while it is being saved; a failed save falls back to
  // what is stored.
  const chosen = update.isPending ? update.variables.stock_basis : preferences.data?.stock_basis;

  return (
    <section className="grid max-w-3xl gap-4">
      <h1 className="font-display text-2xl font-semibold tracking-tight">{t("settings.title")}</h1>
      <p className="text-muted">{t("settings.intro")}</p>
      {preferences.isPending && <p className="text-muted">{t("settings.loading")}</p>}
      {preferences.isError && (
        <p role="alert" className="text-crit">
          {t("settings.error")}
        </p>
      )}
      {preferences.data && (
        <Block title={t("settings.stock.title")}>
          <fieldset className="grid gap-3" aria-describedby={hintId}>
            <legend className="font-medium">{t("settings.stock.basis.legend")}</legend>
            <p id={hintId} className="text-sm text-muted">
              {t("settings.stock.basis.hint")}
            </p>
            {BASES.map((basis) => (
              <label key={basis} className="flex items-start gap-3">
                <input
                  type="radio"
                  name="stock-basis"
                  value={basis}
                  checked={chosen === basis}
                  onChange={() => update.mutate({ ...preferences.data, stock_basis: basis })}
                  className="mt-1"
                />
                <span className="grid">
                  <span className="font-medium">{t(`settings.stock.basis.${basis}.label`)}</span>
                  <span className="text-sm text-muted">
                    {t(`settings.stock.basis.${basis}.detail`)}
                  </span>
                </span>
              </label>
            ))}
          </fieldset>
          {update.isSuccess && (
            <p role="status" className="text-sm text-muted">
              {t("settings.saved")}
            </p>
          )}
          {update.isError && (
            <p role="alert" className="text-sm text-crit">
              {t("settings.saveError")}
            </p>
          )}
        </Block>
      )}
    </section>
  );
}
