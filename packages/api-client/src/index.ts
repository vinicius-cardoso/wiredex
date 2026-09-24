import createClient from "openapi-fetch";
import type { components, paths } from "./generated/schema";

export type { Middleware } from "openapi-fetch";
export type { components, paths };
export type Schemas = components["schemas"];
export type VersionInfo = Schemas["VersionResponse"];
export type UserInfo = Schemas["UserResponse"];
export type SessionInfo = Schemas["SessionResponse"];

export function createApiClient(baseUrl: string) {
  // Look fetch up on every request instead of capturing it now, so anything that
  // wraps it later (test mocks, tracing) is honoured.
  return createClient<paths>({ baseUrl, fetch: (request) => globalThis.fetch(request) });
}

export type ApiClient = ReturnType<typeof createApiClient>;
