import { randomBytes } from "node:crypto";
import { resolve } from "node:path";
import { defineConfig } from "@playwright/test";

const port = Number(process.env.CITATION_TEST_PORT || 18126);
const baseURL = `http://127.0.0.1:${port}`;
// Workers inherit the disposable accounts chosen by the test runner.
process.env.CITATION_TEST_COORDINATOR ??= randomBytes(24).toString("hex");
process.env.CITATION_TEST_INSURER ??= randomBytes(24).toString("hex");

process.env.TEST_LAKESIDE_COORDINATOR ??= randomBytes(24).toString("hex");
process.env.TEST_LAKESIDE_INSURER ??= randomBytes(24).toString("hex");

export default defineConfig({
  testDir: ".",
  outputDir: "../../.local/browser-tests",
  use: { baseURL },
  webServer: {
    cwd: resolve(__dirname, "../.."),
    command: "uv run --locked python -m demo.serve",
    url: baseURL + "/h/canal-bridge/api/access/session",
    reuseExistingServer: false,
    gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 },
    env: {
      DEMO_PORT: String(port),
      DEMO_PASSWORD: process.env.CITATION_TEST_COORDINATOR,
      DEMO_INSURER_PASSWORD: process.env.CITATION_TEST_INSURER,
    },
  },
});
