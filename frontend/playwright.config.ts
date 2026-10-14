import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests run against a running stack (`docker compose up` or `make dev`).
 * The backend should use LLM_PROVIDER=fake so answers are deterministic.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  // Every spec signs up a fresh account (bcrypt) against one API process; keep it modest.
  workers: 2,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
