import type { Middleware } from "@wiredex/api-client";

// Set by the API at login, next to the HttpOnly session cookie (ADR 0008).
export const CSRF_COOKIE = "__Host-wiredex_csrf";
export const CSRF_HEADER = "X-CSRF-Token";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/**
 * Echoes the CSRF cookie in a header on every write. Another site can make the
 * browser send the cookies, but it can't read this one, so it can't copy it.
 */
export function csrfMiddleware(readToken: () => string | undefined): Middleware {
  return {
    onRequest({ request }) {
      const token = readToken();
      if (token && !SAFE_METHODS.has(request.method)) request.headers.set(CSRF_HEADER, token);
      return request;
    },
  };
}

export function readCookie(name: string, cookies = document.cookie): string | undefined {
  for (const pair of cookies.split("; ")) {
    const [key, ...value] = pair.split("=");
    if (key === name) return decodeURIComponent(value.join("="));
  }
  return undefined;
}
