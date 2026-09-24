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
