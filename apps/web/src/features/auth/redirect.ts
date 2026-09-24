/**
 * Where to go after logging in. Only paths on this site: "//evil.example" and
 * "https://..." would send a freshly logged-in user somewhere else (an open redirect).
 */
export function safeRedirect(value: unknown): string | undefined {
  if (typeof value !== "string" || !value.startsWith("/")) return undefined;
  if (value.startsWith("//") || value.startsWith("/\\")) return undefined;
  return value;
}
