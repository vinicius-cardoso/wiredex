import { fileURLToPath } from "node:url";

/** The account every journey logs in as. auth.setup.ts creates it with the CLI. */
export const OWNER = {
  email: "e2e-owner@example.com",
  name: "E2E Owner",
  password: "e2e correct horse battery",
};

/** Cookies of a logged-in browser, saved once by auth.setup.ts and reused by every test. */
export const AUTH_FILE = fileURLToPath(new URL("../.auth/owner.json", import.meta.url));

export const API_DIR = fileURLToPath(new URL("../../apps/api", import.meta.url));

/** A browser that has never logged in. */
export const LOGGED_OUT = { cookies: [], origins: [] };
