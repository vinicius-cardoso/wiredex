import { availableParallelism } from "node:os";
import { defineConfig, devices } from "@playwright/test";
import { AUTH_FILE } from "./tests/owner";

// The web preview proxies /api to the API port (see apps/web/vite.config.ts).
const API_PORT = 9000;
const WEB_PORT = 4173;
const CI = Boolean(process.env.CI);
// Every journey talks to one API process, as production runs it (ADR 0009). Twelve browsers
// kept it busy the whole run: requests queued for seconds, and a step somewhere timed out
// each time. Six leave it room and finish about as soon. Below that, Playwright's own
// default: half the cores.
const WORKERS = Math.max(1, Math.min(6, Math.floor(availableParallelism() / 2)));

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  workers: WORKERS,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  reporter: CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
  },
  // "setup" logs in once; the journeys start from its saved cookies, and the ones
  // about logging in opt out with an empty storage state.
  projects: [
    { name: "setup", testMatch: /.*\.setup\.ts/ },
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], storageState: AUTH_FILE },
      dependencies: ["setup"],
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 7"], storageState: AUTH_FILE },
      dependencies: ["setup"],
    },
  ],
  // Postgres must already be running (make db, or the CI job). Waiting on the
  // readiness endpoint means tests only start once the API can reach it.
  webServer: [
    {
      // Migrate first: that also gives the API's database role its login.
      command: `uv run --directory ../apps/api wiredex db upgrade && uv run --directory ../apps/api uvicorn wiredex.bootstrap.app:create_app --factory --port ${API_PORT}`,
      url: `http://localhost:${API_PORT}/api/health/ready`,
      reuseExistingServer: !CI,
      timeout: 60_000,
    },
    {
      // The production build, not the dev server: that is what users get.
      command: `pnpm --filter @wiredex/web build && pnpm --filter @wiredex/web exec vite preview --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: !CI,
      timeout: 120_000,
    },
  ],
});
