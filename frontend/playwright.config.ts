import { defineConfig } from "@playwright/test";

// End-to-end tests drive the built UI against the real Python server.
// `npm run e2e` builds the UI first; `e2e/serve.mjs` starts the server on a
// throwaway database with model-backed policies off.
//
// The tests use a browser that is already installed, so nothing is downloaded:
// Edge on Windows, Chrome elsewhere. Override with CASEFORGE_E2E_BROWSER
// (msedge, chrome, or chromium for Playwright's own build after
// `npx playwright install chromium`).
const port = Number(process.env.CASEFORGE_E2E_PORT ?? 8791);
const browser = process.env.CASEFORGE_E2E_BROWSER ?? (process.platform === "win32" ? "msedge" : "chrome");

export default defineConfig({
  testDir: "e2e",
  // One server and one database are shared, and every test creates its own runs.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    browserName: "chromium",
    channel: browser === "chromium" ? undefined : browser,
    viewport: { width: 1600, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "node e2e/serve.mjs",
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
