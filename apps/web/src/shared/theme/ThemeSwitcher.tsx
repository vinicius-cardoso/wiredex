import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { iconButton, MonitorIcon, MoonIcon, SunIcon } from "../ui/icons";
import { useTheme } from "./ThemeProvider";
import { type ThemePreference, themePreferences } from "./theme";

const icons: Record<ThemePreference, ReactNode> = {
  light: <SunIcon />,
  dark: <MoonIcon />,
  system: <MonitorIcon />,
};

/**
 * One button for the three themes, to keep the header on one line: it shows the theme in use
 * as a sun, a moon or a screen, and a click moves to the next. Its name says both, since the
 * icon alone tells a screen reader nothing.
 */
export function ThemeSwitcher() {
  const { t } = useTranslation();
  const { preference, setPreference } = useTheme();
  const next =
    themePreferences[(themePreferences.indexOf(preference) + 1) % themePreferences.length];
  const name = t("theme.switch", {
    current: t(`theme.${preference}`),
    next: t(`theme.${next ?? "system"}`),
  });

  return (
    <button
      type="button"
      aria-label={name}
      title={name}
      onClick={() => setPreference(next ?? "system")}
      className={iconButton}
    >
      {icons[preference]}
    </button>
  );
}
