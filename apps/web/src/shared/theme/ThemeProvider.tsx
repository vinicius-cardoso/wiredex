import {
  createContext,
  type ReactNode,
  use,
  useLayoutEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";
import { preferences } from "../lib/storage";
import {
  applyTheme,
  type ResolvedTheme,
  resolveTheme,
  savedPreference,
  THEME_KEY,
  type ThemePreference,
} from "./theme";

const DARK_QUERY = "(prefers-color-scheme: dark)";

function subscribeToSystemTheme(onChange: () => void) {
  const query = window.matchMedia(DARK_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function systemPrefersDark() {
  return window.matchMedia(DARK_QUERY).matches;
}

type ThemeState = {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
};

const ThemeContext = createContext<ThemeState | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState(savedPreference);
  const systemDark = useSyncExternalStore(subscribeToSystemTheme, systemPrefersDark, () => false);
  const resolved = resolveTheme(preference, systemDark);

  useLayoutEffect(() => {
    applyTheme(resolved);
  }, [resolved]);

  const state = useMemo<ThemeState>(
    () => ({
      preference,
      resolved,
      setPreference(next) {
        preferences.write(THEME_KEY, next);
        setPreferenceState(next);
      },
    }),
    [preference, resolved],
  );

  return <ThemeContext value={state}>{children}</ThemeContext>;
}

export function useTheme(): ThemeState {
  const state = use(ThemeContext);
  if (!state) throw new Error("useTheme must be used inside <ThemeProvider>");
  return state;
}
