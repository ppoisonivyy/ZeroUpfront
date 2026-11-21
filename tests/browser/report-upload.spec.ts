import { createHash } from "node:crypto";
import { expect, test } from "@playwright/test";

test("an uploaded image and scanned PDF require visual review before the payer receives the report", async ({ browser, page, request }) => {
  const hospital = "/h/lakeside";
  const api = hospital + "/api";
  const staff = await page.request.post(api + "/access/login", {
    data: { username: "upload-coordinator", password: process.env.TEST_LAKESIDE_COORDINATOR },
  });
  expect(staff.status()).toBe(200);
  // Create synthetic physical originals in memory. Both pages of the PDF contain pixels only.
  const exhibit = await browser.newPage({ viewport: { width: 780, height: 480 } });
  await exhibit.setContent(`<main style="padding:36px;font:20px sans-serif">
    <h1>Fictional physician report</h1><p>Amelia Morgan · DEMO-MA-0248 · ZU-0248</p>
    <p>Lakeside Demo Hospital · Inpatient knee arthroscopy</p>
    <p>Indication: persistent mechanical symptoms.</p>
    <p>Treating physician mark (synthetic)</p>
    <svg width="250" height="60" viewBox="0 0 250 60"><path d="M10 48Q40 0 34 35T64 25Q52 60 85 32L120 28" stroke="#173b50" fill="none" stroke-width="3"/></svg>
  </main>`);
  const image = await exhibit.screenshot();
  const picture = `<img style="max-width:100%" src="data:image/png;base64,${image.toString("base64")}"/>`;
  await exhibit.setContent('<p>Fictional training document • Cover sheet</p>');
  const cover = await exhibit.screenshot();
  await exhibit.setContent(`<style>@page {size:A4;margin:12mm}</style>
    <div style="break-after:page"><img style="max-width:100%" src="data:image/png;base64,${cover.toString("base64")}"></div>${picture}`);
  const scan = await exhibit.pdf({ preferCSSPageSize: true });
  await exhibit.close();

  await page.goto(hospital + "/#/preclaims/ZU-0248");
  async function upload(name: string, mimeType: string, buffer: Buffer) {
    await page.getByText("Upload a physician report", { exact: true }).click();
    await page.getByLabel("Physician report file", { exact: true }).setInputFiles({ name, mimeType, buffer });
    await page.getByLabel("I intend to attach this file").check();
    await page.getByRole("button", { name: "Save report for visual review" }).click();
  }
  await upload("synthetic-report.png", "image/png", image);
  const viewer = page.getByRole("region", { name: "Original physician report" });
  await expect(viewer.getByRole("img", { name: "Uploaded physician report, page 1" })).toBeVisible();
  await expect(viewer.getByRole("button", { name: "Record review of page 1" })).toBeDisabled();
  const firstOriginal = await viewer.getByRole("link", { name: "Open original" }).getAttribute("href");
  expect(await (await page.request.get(firstOriginal!)).body()).toEqual(image);
  await expect(page.getByText("Send report to OpenAI")).toHaveCount(0);

  // Exercise the opt-in UI contract without sending a document to a provider.
  const detailRoute = "**/api/preclaims/ZU-0248";
  const hintRoute = "**/api/preclaims/ZU-0248/revisions/2/report-signature-hint";
  const sha256 = createHash("sha256").update(image).digest("hex");
  let hintRequests = 0;
  await page.route(detailRoute, async route => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...await response.json(), report_signature_hint_enabled: true } });
  });
  await page.route(hintRoute, async route => {
    hintRequests++;
    expect(route.request().postDataJSON()).toEqual({ confirmed: true, sha256 });
    await route.fulfill({ json: { status: "suggested", pages: [1], revision: 2, sha256 } });
  });
  await page.reload();
  await page.getByRole("button", { name: "Inspect uploaded report" }).click();
  await viewer.getByText("Find a possible signature page", { exact: true }).click();
  expect(hintRequests).toBe(0);
  await viewer.getByRole("button", { name: "Send report to OpenAI" }).click();
  await expect(viewer.getByText(/Possible signature on page 1/)).toBeVisible();
  await expect(viewer.getByRole("button", { name: "Record review of page 1" })).toBeDisabled();
  await page.unroute(detailRoute);
  await page.unroute(hintRoute);

  await upload("synthetic-scan.pdf", "application/pdf", scan);
  await expect(viewer.getByRole("img", { name: "Original physician report, page 1" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Mark draft reviewed" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Submit to insurer desk" })).toHaveCount(0);
  await expect(viewer.locator(".pdf-quote-mark")).toHaveCount(0);
  const confirmIdentity = viewer.getByRole("checkbox", { name: /I matched Amelia Morgan/ });
  await confirmIdentity.check();
  await expect(viewer.getByRole("button", { name: "Record review of page 1" })).toBeDisabled();
  await viewer.getByRole("button", { name: "Next" }).click();
  await expect(viewer.getByRole("img", { name: "Original physician report, page 2" })).toBeVisible();
  await expect(confirmIdentity).not.toBeChecked();
  await confirmIdentity.check();
  await viewer.getByRole("checkbox", { name: /physician’s signature or mark on page 2/ }).check();
  await viewer.getByRole("button", { name: "Record review of page 2" }).click();
  await expect(viewer.getByText(/recorded a visible physician mark on page 2/)).toBeVisible();
  await page.getByRole("button", { name: "Review insurer form" }).click();
  await page.getByRole("button", { name: "Mark draft reviewed" }).click();
  await page.getByRole("button", { name: "Submit to insurer desk" }).click();
  await expect(page.getByRole("heading", { name: "Waiting for insurer" })).toBeVisible();
  expect(await (await page.request.get(firstOriginal!)).body()).toEqual(image);

  expect((await request.post(api + "/access/login", {
    data: { username: "upload-insurer", password: process.env.TEST_LAKESIDE_INSURER },
  })).status()).toBe(200);
  const received = await (await request.get(api + "/insurer/preclaims/ZU-0248?revision=4")).json();
  expect(received.report_evidence.page).toBe(2);
  expect(received.report_evidence.status).toBe("staff_attested");
  expect(await (await request.get(received.report_evidence.original_url)).body()).toEqual(scan);
});
