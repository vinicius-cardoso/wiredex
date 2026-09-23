import { preferences } from "../lib/storage";

export const themePreferences = ["light", "dark", "system"] as const;
export type ThemePreference = (typeof themePreferences)[number];
export type ResolvedTheme = "light" | "dark";

// Keep in sync with public/theme-init.js, which runs before first paint.
export const THEME_KEY = "wiredex.theme";

export function isThemePreference(value: unknown): value is ThemePreference {
  return themePreferences.some((preference) => preference === value);
}

export function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme {
  if (preference !== "system") return preference;
  return systemPrefersDark ? "dark" : "light";
}

export function savedPreference(): ThemePreference {
  const saved = preferences.read(THEME_KEY);
  return isThemePreference(saved) ? saved : "system";
}

export function applyTheme(theme: ResolvedTheme, root: HTMLElement = document.documentElement) {
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
}
