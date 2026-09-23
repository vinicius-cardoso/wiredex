/**
 * localStorage that never throws. Private windows and blocked site data make the
 * real one throw on access; preferences are a convenience, so fall back to nothing.
 */
export const preferences = {
  read(key: string): string | null {
    try {
      return globalThis.localStorage?.getItem(key) ?? null;
    } catch {
      return null;
    }
  },
  write(key: string, value: string): void {
    try {
      globalThis.localStorage?.setItem(key, value);
    } catch {
      // Not persisted; the choice still applies for this session.
    }
  },
};
