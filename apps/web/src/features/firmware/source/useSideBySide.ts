import { useSyncExternalStore } from "react";

/** Two panes of code need about this much: below it each would hold a few words a line. */
const QUERY = "(min-width: 64rem)";

function subscribe(onChange: () => void) {
  const media = window.matchMedia(QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

/**
 * Whether a comparison shows its two versions side by side, as an editor's diff does once its
 * window is wide enough, or as one column of changes. It follows the window as it is resized.
 */
export function useSideBySide(): boolean {
  return useSyncExternalStore(subscribe, () => window.matchMedia(QUERY).matches);
}
