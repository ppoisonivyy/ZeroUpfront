import { expect, test } from "@playwright/test";

test("an insurer question opens its submitted page without borrowing a passage", async ({ page, request }) => {
  const hospital = "/h/canal-bridge";
  const api = hospital + "/api";
  const hospitalLogin = await request.post(api + "/access/login", {
    data: { username: "film-hospital", password: process.env.CITATION_TEST_COORDINATOR },
  });
  expect(hospitalLogin.status()).toBe(200);
  for (const [action, revision] of [["attach-report", 1], ["review", 2], ["submit", 2]] as const) {
    const saved = await request.post(api + "/preclaims/ZU-0248/" + action, {
      headers: { "If-Match": `"${revision}"` }, data: { confirmed: true },
    });
    expect(saved.status()).toBe(200);
  }
  const insurerLogin = await page.request.post(api + "/access/login", {
    data: { username: "film-insurer", password: process.env.CITATION_TEST_INSURER },
  });
  expect(insurerLogin.status()).toBe(200);
  await page.goto(hospital + "/#/insurer/ZU-0248?revision=2");
  const viewer = page.getByRole("region", { name: "Source viewer" });
  // The submitted policy includes a separately verified quote on page 12.
  await page.getByRole("button", { name: "Global Select policy wording", exact: true }).click();
  await expect(viewer.locator('[data-citation-status="matched"]')).toBeVisible();
  await expect(viewer.locator(".pdf-quote-mark").first()).toBeVisible();

  const questions = page.getByRole("region", { name: "Packet clarification" });
  await questions.getByRole("button", { name: "Ask about this packet" }).click();
  await questions.getByLabel("Document").selectOption("policy");
  await questions.getByLabel("Page", { exact: true }).fill("12");
  await questions.getByRole("textbox").fill("Which admission date does this page apply to?");
  await questions.getByRole("button", { name: "Send question to hospital" }).click();
  const citation = questions.getByRole("button", { name: /Global Select policy wording.*p\. 12/ });
  await citation.click();
  await expect(viewer.locator('[data-citation-status="no-quote"]')).toBeVisible();
  await expect(viewer.locator(".pdf-quote-mark, .recorded-summary")).toHaveCount(0);

  const pageNumber = viewer.getByRole("spinbutton");
  const original = viewer.getByRole("link", { name: "Open PDF" });
  await viewer.getByRole("button", { name: "Previous" }).click();
  await expect(pageNumber).toHaveValue("11");
  await expect(original).toHaveAttribute("href", /#page=11$/);
  await viewer.getByRole("button", { name: "Back to review task" }).click();
  await expect(citation).toBeFocused();
  await citation.click();
  await expect(pageNumber).toHaveValue("12");
  await expect(viewer.getByRole("img", { name: /page 12$/ })).toBeVisible();
  await expect(original).toHaveAttribute("href", /#page=12$/);
  await expect(viewer.locator('[data-citation-status="no-quote"]')).toBeVisible();
  await expect(viewer.locator(".pdf-quote-mark")).toHaveCount(0);
});
