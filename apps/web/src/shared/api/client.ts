import { createApiClient } from "@wiredex/api-client";
import { CSRF_COOKIE, csrfMiddleware, readCookie } from "./csrf";

// Same origin in every environment: Vite proxies /api in development, Caddy in production.
export const api = createApiClient(window.location.origin);
api.use(csrfMiddleware(() => readCookie(CSRF_COOKIE)));
