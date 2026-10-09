// jsdom has no matchMedia. Tests flip the OS theme with setSystemDark(), and the window's
// width past any `min-width` with setWideScreen().
type Listener = () => void;

let systemDark = false;
let wideScreen = false;
const listeners = new Set<Listener>();

export function setSystemDark(value: boolean) {
  systemDark = value;
  for (const listener of listeners) listener();
}

export function setWideScreen(value: boolean) {
  wideScreen = value;
  for (const listener of listeners) listener();
}

export function resetMatchMedia() {
  systemDark = false;
  wideScreen = false;
  listeners.clear();
}

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    media: query,
    get matches() {
      return query.includes("dark") ? systemDark : query.includes("min-width") && wideScreen;
    },
    onchange: null,
    addEventListener: (_type: string, listener: Listener) => listeners.add(listener),
    removeEventListener: (_type: string, listener: Listener) => listeners.delete(listener),
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }),
});
