// jsdom has no matchMedia. Tests flip the OS theme with setSystemDark().
type Listener = () => void;

let systemDark = false;
const listeners = new Set<Listener>();

export function setSystemDark(value: boolean) {
  systemDark = value;
  for (const listener of listeners) listener();
}

export function resetMatchMedia() {
  systemDark = false;
  listeners.clear();
}

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    media: query,
    matches: query.includes("dark") && systemDark,
    onchange: null,
    addEventListener: (_type: string, listener: Listener) => listeners.add(listener),
    removeEventListener: (_type: string, listener: Listener) => listeners.delete(listener),
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }),
});
