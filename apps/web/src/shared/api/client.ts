import { createApiClient } from "@wiredex/api-client";

// Same origin in every environment: Vite proxies /api in development, Caddy in production.
export const api = createApiClient(window.location.origin);
