import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { mkdir } from "node:fs/promises";
import assert from "node:assert/strict";
const root = resolve("..");
const backend = spawn(
  resolve(root, ".venv/Scripts/python.exe"),
  [
    "-m",
    "uvicorn",
    "backend.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    "18013",
  ],
  { cwd: root, windowsHide: true, stdio: "inherit" },
);
const vite = spawn(
  process.execPath,
  [
    resolve("node_modules/vite/bin/vite.js"),
    "--host",
    "127.0.0.1",
    "--port",
    "15175",
    "--strictPort",
  ],
  {
    cwd: resolve("."),
    env: { ...process.env, CORECARE_BACKEND_URL: "http://127.0.0.1:18013" },
    windowsHide: true,
    stdio: "inherit",
  },
);
async function ready(url) {
  for (let i = 0; i < 600; i++) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 200));
  }
  throw Error("Verification server unavailable");
}

let browser;
try {
  await mkdir(resolve(root, "docs/screenshots"), { recursive: true });
  await Promise.all([
    ready("http://127.0.0.1:18013/config"),
    ready("http://127.0.0.1:15175"),
  ]);
  browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({
    viewport: { width: 1920, height: 1080 },
    reducedMotion: "reduce",
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const capture = async (name) => {
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(400);
    assert.equal(await page.getByRole("alert").count(), 0);
    await page.screenshot({
      path: resolve(root, "docs/screenshots", name),
      animations: "disabled",
    });
    console.log("Captured " + name);
  };
  await page.goto("http://127.0.0.1:15175");
  await capture("dashboard.png");
  await page
    .getByRole("button", { name: "Medical Report Analysis", exact: true })
    .click();
  await capture("report-analyzer.png");
  await page
    .getByLabel("Medical report file")
    .setInputFiles(resolve(root, "tests/fixtures/reports/cbc_text.pdf"));
  await capture("report-upload.png");
  await page.getByRole("checkbox").check();
  const pending = page.waitForResponse(
    (r) =>
      r.url().endsWith("/reports/analyze") && r.request().method() === "POST",
    { timeout: 150000 },
  );
  await page.getByRole("button", { name: /Analyze Report/ }).click();
  const response = await pending;
  assert.equal(response.status(), 200);
  const report = await response.json();
  assert.equal(report.status, "completed");
  assert.equal(report.external_llm_used, true);
  assert.equal(report.explanation.mode, "llm_assisted");
  assert.ok(report.sources.some((s) => s.type === "reference" && s.url));
  await page
    .getByRole("heading", { name: "Understanding Your Report" })
    .waitFor();
  while (await page.locator(".parameter-card details[open] > summary").count())
    await page
      .locator(".parameter-card details[open] > summary")
      .first()
      .click();
  await page.locator(".agent-body").evaluate((el) => (el.scrollTop = 280));
  await capture("analysis-results.png");
  await page
    .getByRole("button", {
      name: "Maximize Medical Report Analysis",
      exact: true,
    })
    .click();
  await page.locator(".agent-body").evaluate((el) => (el.scrollTop = 0));
  await capture("maximized-view.png");
  await page
    .locator(".parameter-card")
    .first()
    .getByText("What does this parameter measure?", { exact: true })
    .click();
  for (const s of await page
    .locator(".source")
    .filter({ hasText: "External knowledge source" })
    .all())
    if ((await s.getAttribute("open")) === null)
      await s.locator("summary").click();
  await page.locator(".agent-body").evaluate((el) => (el.scrollTop = 390));
  await capture("ai-explanations.png");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator(".agent-body").evaluate((el) => (el.scrollTop = 0));
  await capture("mobile-view.png");
  assert.deepEqual(errors, []);
  console.log(
    JSON.stringify({
      status: report.status,
      external_llm_used: report.external_llm_used,
      mode: report.explanation.mode,
      source_count: report.sources.length,
      browser_errors: errors,
    }),
  );
} finally {
  await browser?.close();
  vite.kill();
  backend.kill();
}
