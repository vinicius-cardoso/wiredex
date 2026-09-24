import { describe, expect, it } from "vitest";
import { CSRF_HEADER, csrfMiddleware, readCookie } from "./csrf";

async function headerSentWith(method: string, token: string | undefined) {
  const middleware = csrfMiddleware(() => token);
  const request = new Request("https://wiredex.test/api/auth/logout", { method });
  // Only onRequest is used; the other fields openapi-fetch passes don't matter here.
  const sent = await middleware.onRequest?.({ request } as never);
  return (sent as Request).headers.get(CSRF_HEADER);
}

describe("csrfMiddleware", () => {
  it("echoes the token on writes", async () => {
    expect(await headerSentWith("POST", "t0ken")).toBe("t0ken");
    expect(await headerSentWith("DELETE", "t0ken")).toBe("t0ken");
  });

  it("leaves reads, and requests before any login, alone", async () => {
    expect(await headerSentWith("GET", "t0ken")).toBeNull();
    expect(await headerSentWith("POST", undefined)).toBeNull();
  });
});

describe("readCookie", () => {
  it("finds a cookie by its exact name", () => {
    const cookies = "theme=dark; __Host-wiredex_csrf=a%3Db=c; other=1";

    expect(readCookie("__Host-wiredex_csrf", cookies)).toBe("a=b=c");
    expect(readCookie("wiredex_csrf", cookies)).toBeUndefined();
  });
});
