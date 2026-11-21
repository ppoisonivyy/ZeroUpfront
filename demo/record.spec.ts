// Run from the repository root with npm run demo:record.
import { test, chromium, expect, type Page } from "@playwright/test";
import { execFileSync, spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import {
  createWriteStream,
  mkdirSync,
  mkdtempSync,
  writeFileSync,
} from "node:fs";
import { resolve } from "node:path";
import { Director } from "./director";
import { showHoldout } from "./terminal";

const port = Number(process.env.DEMO_PORT || 18092);
const origin = "http://127.0.0.1:" + port;
const caseName = /Amelia Morgan/i;
const scratch = resolve(".local/storyboard");

async function card(page: Page, title: string, detail: string) {
  await page.goto("about:blank");
  await page.setContent(
    '<main style="min-height:100vh;display:grid;align-content:center;justify-content:start;box-sizing:border-box;padding:9vw;background:#1f4d3f;color:white;font-family:Arial,sans-serif"><p style="font-size:30px;margin:0 0 28px;color:#c6e1cf"></p><h1 style="font-size:76px;line-height:1.08;max-width:1500px;margin:0"></h1></main><style>body{margin:0}</style>',
  );
  await page
    .locator("main p")
    .evaluate((p, value) => (p.textContent = value), detail);
  await page
    .locator("h1")
    .evaluate((p, value) => (p.textContent = value), title);
}

async function signIn(page: Page, username: string, password: string) {
  await page
    .getByRole("textbox", { name: "Username", exact: true })
    .fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toHaveCount(0);
}

async function recordHandoff(
  page: Page,
  d: Director,
  hospitalPassword: string,
  insurerPassword: string,
) {
  await page.goto(origin + "/h/canal-bridge/");
  await signIn(page, "film-hospital", hospitalPassword);
  await page
    .getByRole("link", { name: "Pre-arrival cases", exact: true })
    .click();
  await d.step(
    2,
    "The hospital desk's queue. Synthetic patients only.",
    async () => {
      await expect(
        page.getByRole("heading", { name: "Hospital work queue" }),
      ).toBeVisible();
      await expect(page.getByRole("link", { name: caseName })).toBeVisible();
    },
  );
  await d.step(
    3,
    "Amelia’s knee surgery needs insurer preauthorization.",
    async () => {
      await d.click(page.getByRole("link", { name: caseName }));
      await expect(page.getByRole("heading", { name: caseName })).toBeVisible();
      await expect(
        page.getByText(/inpatient knee arthroscopy/i).first(),
      ).toBeVisible();
    },
  );
  await d.step(
    4,
    "Missing signature. Code verifies this rule on page 12.",
    async () => {
      await d.click(page.getByRole("button", { name: "View cited clause" }));
      const clause = page
        .locator("blockquote")
        .filter({ hasText: /signed/i })
        .first();
      await expect(clause).toBeVisible();
      await d.highlight(clause);
    },
  );
  await d.step(
    5,
    "The desk attaches the signed report. The gap clears.",
    async () => {
      await d.click(
        page.getByRole("button", { name: /Attach signed (sample )?report/i }),
      );
      await expect(
        page.getByRole("button", { name: "Review insurer form" }),
      ).toBeVisible();
    },
  );
  const formCaption = "Staff review and send the request. The insurer decides.";
  await d.step(6, formCaption, async () => {
    await d.click(page.getByRole("button", { name: "Review insurer form" }));
    await expect(
      page.getByRole("button", { name: "Mark draft reviewed" }),
    ).toBeEnabled();
    await expect(page.locator("canvas").first()).toBeVisible();
  });
  await d.step(61, formCaption, async () => {
    await d.click(page.getByRole("button", { name: "Mark draft reviewed" }));
    await d.click(page.getByRole("button", { name: "Submit to insurer desk" }));
    await expect(page.getByText(/Waiting for insurer/i).first()).toBeVisible();
  });
  // Reauthentication is real; cut it from the film to keep credentials off screen.
  const inboxCaption = "Meridian Assist receives Amelia’s reviewed request.";
  await d.step(70, inboxCaption, async () => {
    await d.click(
      page.getByTitle("Canal Bridge Demo Hospital", { exact: true }),
    );
    await expect(
      page.getByRole("button", { name: "Switch to insurer desk" }),
    ).toBeVisible();
  });
  await page.getByRole("button", { name: "Switch to insurer desk" }).click();
  await signIn(page, "film-insurer", insurerPassword);
  await d.step(7, inboxCaption, async () => {
    await expect(
      page.getByRole("heading", { name: "Insurer inbox" }),
    ).toBeVisible();
    await d.click(page.getByRole("link", { name: caseName }));
    await expect(page.getByRole("heading", { name: caseName })).toBeVisible();
  });
  await page
    .getByRole("button", { name: "Meridian Assist", exact: true })
    .click();
  await page.getByRole("button", { name: "Switch to hospital desk" }).click();
  await signIn(page, "film-hospital", hospitalPassword);
  await d.step(
    8,
    "Hospital queue: waiting for the insurer’s decision.",
    async () => {
      await expect(
        page.getByRole("heading", { name: "Hospital work queue" }),
      ).toBeVisible();
      await page
        .getByRole("combobox", { name: "Work queue" })
        .selectOption({ label: "Waiting for insurer" });
      await expect(page.getByRole("link", { name: caseName })).toBeVisible();
    },
  );
}

test("record the actual hospital-to-insurer journey", async () => {
  mkdirSync(scratch, { recursive: true });
  const run = mkdtempSync(scratch + "/take-");
  const credentials = [
    randomBytes(24).toString("base64url"),
    randomBytes(24).toString("base64url"),
  ];
  const log = createWriteStream(run + "/server.log");
  // Never attach the recorder to an existing service; it submits a real revision.
  const occupied = await fetch(origin + "/healthz", {
    signal: AbortSignal.timeout(800),
  })
    .then(() => true)
    .catch(() => false);
  expect(occupied, "Choose a free DEMO_PORT for the private recording").toBe(
    false,
  );
  const service = spawn(
    "uv",
    ["run", "--locked", "python", "-m", "demo.serve"],
    {
      env: {
        ...process.env,
        DEMO_PORT: String(port),
        DEMO_PASSWORD: credentials[0],
        DEMO_INSURER_PASSWORD: credentials[1],
      },
      detached: true,
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  service.stdout.pipe(log, { end: false });
  service.stderr.pipe(log, { end: false });
  const stopped = new Promise((resolve) => service.once("exit", resolve));
  try {
    await expect
      .poll(
        async () => {
          if (service.exitCode !== null)
            throw new Error(
              "Disposable server exited. See " + run + "/server.log",
            );
          return fetch(origin + "/readyz")
            .then((r) => r.status)
            .catch(() => 0);
        },
        { timeout: 40000 },
      )
      .toBe(204);
    const browser = await chromium.launch({ headless: true, slowMo: 250 });
    try {
      const context = await browser.newContext({
        viewport: { width: 1920, height: 1080 },
        deviceScaleFactor: 1,
        recordVideo: { dir: run, size: { width: 1920, height: 1080 } },
        reducedMotion: "reduce",
      });
      const page = await context.newPage();
      page.setDefaultTimeout(6000);
      const video = page.video()!;
      const d = new Director(page);
      await card(
        page,
        "ZeroUpfront: hospital guarantee requests with no questions back",
        "Synthetic case walkthrough",
      );
      await d.step(1, "", async () => {}, 3000);
      try {
        await recordHandoff(page, d, ...(credentials as [string, string]));
      } catch (error) {
        for (let id = 2; id <= 8; id++)
          if (
            !d.scenes.some((s) => s.id === id) &&
            !d.skipped.some((s) => s.id === id)
          )
            d.skip(
              id,
              "The required screen could not be reached. " +
                String(error).split("\n")[0].slice(0, 120),
            );
      }
      await d.step(
        9,
        "Tested on held-out cases from known payer forms.",
        () => showHoldout(page),
        4000,
      );
      await card(
        page,
        "Built with Codex at the Sea x OpenAI Regional Codex Hackathon, 21 Nov 2026",
        "github.com/aowngong/ZeroUpfront",
      );
      await d.step(10, "", async () => {}, 3000);
      await context.close();
      const file = await video.path();
      const metadata = run + "/take.json";
      writeFileSync(
        metadata,
        JSON.stringify({ scenes: d.scenes, skipped: d.skipped }, null, 2),
      );
      execFileSync("python3", ["demo/render.py", metadata, file], {
        stdio: "inherit",
      });
    } finally {
      await browser.close();
    }
  } finally {
    if (service.pid && service.exitCode === null)
      process.kill(-service.pid, "SIGTERM");
    await Promise.race([stopped, new Promise((r) => setTimeout(r, 2500))]);
    log.end();
  }
});
