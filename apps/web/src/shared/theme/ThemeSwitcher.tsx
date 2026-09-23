import { useTranslation } from "react-i18next";
import { useTheme } from "./ThemeProvider";
import { themePreferences } from "./theme";

export function ThemeSwitcher() {
  const { t } = useTranslation();
  const { preference, setPreference } = useTheme();

  return (
    <fieldset className="flex items-center gap-2 text-sm">
      <legend className="sr-only">{t("theme.label")}</legend>
      <div className="inline-flex overflow-hidden rounded-md border border-border-strong">
        {themePreferences.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={preference === option}
            onClick={() => setPreference(option)}
            className="px-3 py-1 text-muted not-first:border-l not-first:border-border aria-pressed:bg-primary aria-pressed:text-on-primary"
          >
            {t(`theme.${option}`)}
          </button>
        ))}
      </div>
    </fieldset>
  );
}
