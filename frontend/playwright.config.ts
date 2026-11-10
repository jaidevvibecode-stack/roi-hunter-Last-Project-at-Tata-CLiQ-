import { defineConfig } from "@playwright/test";

const PY = process.env.PYTHON ?? "python3";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 45_000,
  expect: { timeout: 15_000 },
  retries: process.env.CI ? 1 : 0, // no local retries: a retry once hid a real race condition
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:3100", channel: "chrome", viewport: { width: 1600, height: 1000 }, trace: "retain-on-failure" },
  webServer: [
    {
      command: `"${PY}" -m uvicorn backend.main:app --host 127.0.0.1 --port 8100`,
      cwd: "..",
      env: { ENV: "local", DATA_SOURCE: "demo", PYTHONPATH: ".." },
      url: "http://127.0.0.1:8100/health",
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npm run dev -- -p 3100 -H 127.0.0.1",
      env: { BACKEND_URL: "http://127.0.0.1:8100", NEXT_DIST_DIR: ".next-e2e", UI_AUTH_DISABLED: "true" },
      url: "http://127.0.0.1:3100/healthz",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
