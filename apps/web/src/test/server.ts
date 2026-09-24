import type { SessionInfo } from "@wiredex/api-client";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";

export const server = setupServer();

export function respondWithApiVersion(version: string, commit = "0123456789abcdef") {
  server.use(
    http.get("*/api/version", () => HttpResponse.json({ version, commit, built_at: null })),
  );
}

export function failApiVersion() {
  server.use(http.get("*/api/version", () => HttpResponse.error()));
}

export const OWNER = {
  id: "0199aaaa-0000-7000-8000-000000000001",
  email: "owner@example.com",
  name: "Owner",
  expires_at: null as string | null,
};

export function respondAsLoggedIn(user = OWNER) {
  server.use(http.get("*/api/auth/me", () => HttpResponse.json(user)));
}

export function respondAsLoggedOut() {
  server.use(
    http.get("*/api/auth/me", () => HttpResponse.json({ detail: "log in first" }, { status: 401 })),
  );
}

/** Accepts OWNER's email with the password "correct horse battery". */
export function acceptLogins({ status = 200 } = {}) {
  server.use(
    http.post("*/api/auth/login", async ({ request }) => {
      const body = (await request.json()) as { email: string; password: string };
      const valid = body.email === OWNER.email && body.password === "correct horse battery";
      if (status !== 200) return HttpResponse.json({ detail: "refused" }, { status });
      if (!valid) return HttpResponse.json({ detail: "wrong email or password" }, { status: 401 });
      respondAsLoggedIn();
      return HttpResponse.json(OWNER);
    }),
  );
}

export function acceptLogout() {
  server.use(
    http.post("*/api/auth/logout", () => {
      respondAsLoggedOut();
      return new HttpResponse(null, { status: 204 });
    }),
  );
}

export const FIREFOX_ON_LINUX =
  "Mozilla/5.0 (X11; Linux x86_64; rv:143.0) Gecko/20100101 Firefox/143.0";

export function aSession(overrides: Partial<SessionInfo> = {}): SessionInfo {
  return {
    id: "0199aaaa-0000-7000-8000-0000000000a1",
    device: FIREFOX_ON_LINUX,
    created_at: "2026-09-20T10:00:00Z",
    last_seen_at: "2026-09-24T12:00:00Z",
    current: true,
    ...overrides,
  };
}

/** Lists SESSIONS and deletes from it, like the real API. */
export function respondWithSessions(sessions: SessionInfo[]) {
  let remaining = [...sessions];
  server.use(
    http.get("*/api/auth/sessions", () => HttpResponse.json(remaining)),
    http.delete("*/api/auth/sessions/:id", ({ params }) => {
      remaining = remaining.filter((session) => session.id !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
  );
}
