import { useState } from "react";
import { preferences } from "../../../shared/lib/storage";

/** Beside the theme's `wiredex.theme` and the language's `wiredex.language`. */
export const WRAP_KEY = "wiredex.firmware.wrap";

/**
 * Whether long lines break at the box's width, remembered on this device (requirements 2.2,
 * 2.3). Off unless chosen: a sketch reads as the IDE shows it, a long line scrolling in its box.
 */
export function useWrap(): [boolean, (wrap: boolean) => void] {
  const [wrap, setWrap] = useState(() => preferences.read(WRAP_KEY) === "on");
  function change(next: boolean) {
    setWrap(next);
    preferences.write(WRAP_KEY, next ? "on" : "off");
  }
  return [wrap, change];
}
