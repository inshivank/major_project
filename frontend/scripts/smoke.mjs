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
    "18011",
  ],
  { cwd: root, windowsHide: true, stdio: "ignore" },
);
const vite = spawn(
  process.execPath,
  [
    resolve("node_modules/vite/bin/vite.js"),
    "--host",
    "127.0.0.1",
    "--port",
    "15174",
    "--strictPort",
  ],
  {
    cwd: resolve("."),
    env: { ...process.env, CORECARE_BACKEND_URL: "http://127.0.0.1:18011" },
    windowsHide: true,
    stdio: "ignore",
  },
);
async function ready(url) {
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 200));
  }
  throw Error("Verification server unavailable");
}
let browser;
try {
  await ready("http://127.0.0.1:18011/config");
  await ready("http://127.0.0.1:15174");
  browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  const failures = [];
  page.on("pageerror", (e) => failures.push(e.message));
  await page.goto("http://127.0.0.1:15174");
  await page.getByRole("button", { name: "Medical Report Analysis" }).click();
  await page.getByRole("button", { name: "Browse file" }).waitFor();
  await page.getByLabel("Maximize Medical Report Analysis").click();
  assert.equal(
    await page.getByRole("dialog").getAttribute("aria-modal"),
    "true",
  );
  assert.equal(
    await page.evaluate(() => document.body.style.overflow),
    "hidden",
  );
  await page.keyboard.press("Escape");
  assert.equal(
    await page.getByRole("dialog").getAttribute("aria-modal"),
    "false",
  );
  await page
    .getByLabel("Medical report file")
    .setInputFiles(resolve(root, "tests/fixtures/reports/cbc_text.pdf"));
  await page.getByRole("button", { name: "Analyze Report →" }).click();
  await page
    .getByText("Hemoglobin", { exact: true })
    .waitFor({ timeout: 130000 });
  assert(
    await page.getByText("Below stated range", { exact: true }).isVisible(),
  );
  await page.getByLabel("Maximize Medical Report Analysis").click();
  assert.equal(
    await page
      .locator(".results-grid")
      .evaluate(
        (el) => getComputedStyle(el).gridTemplateColumns.split(" ").length,
      ),
    2,
  );
  await page.getByLabel("Minimize Medical Report Analysis").click();
  await page.getByRole("dialog").waitFor({ state: "hidden" });
  await page.getByRole("button", { name: "Medical Report Analysis" }).click();
  assert.equal(
    await page.getByRole("dialog").getAttribute("aria-modal"),
    "true",
  );
  assert(await page.getByText("Hemoglobin", { exact: true }).isVisible());
  await mkdir(resolve(root, "reports/runtime/ui"), { recursive: true });
  await page
    .getByRole("dialog")
    .evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished)));
  await page.screenshot({
    path: resolve(root, "reports/runtime/ui/desktop.png"),
  });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.getByRole("dialog").evaluate(async (el) => {
    await new Promise(requestAnimationFrame);
    await Promise.all(el.getAnimations().map((a) => a.finished));
  });
  const bounds = await page.getByRole("dialog").boundingBox();
  assert(
    bounds.x >= 0 &&
      bounds.x + bounds.width <= 376 &&
      bounds.y >= 0 &&
      bounds.y + bounds.height <= 813,
  );
  await page.screenshot({
    path: resolve(root, "reports/runtime/ui/mobile.png"),
  });
  assert.equal(
    await page
      .locator(".structured-report .results-grid")
      .evaluate(
        (el) => getComputedStyle(el).gridTemplateColumns.split(" ").length,
      ),
    1,
  );
  assert(
    await page
      .getByRole("heading", { name: "Hemoglobin", exact: true })
      .isVisible(),
  );
  await page.getByRole("button", { name: "Analyze another report" }).click();
  await page.keyboard.press("Escape");
  assert.equal(
    await page.getByRole("dialog").getAttribute("aria-modal"),
    "false",
  );
  await page.keyboard.press("Escape");
  await page.getByRole("dialog").waitFor({ state: "hidden" });
  assert(
    await page
      .getByRole("button", { name: "Medical Report Analysis" })
      .evaluate((e) => e === document.activeElement),
  );
  assert.equal(
    await page.evaluate(() => localStorage.length + sessionStorage.length),
    0,
  );
  assert.deepEqual(failures, []);
  console.log(
    "PASS: real backend PDF upload, range rendering, retained results, mobile bounds, keyboard focus, no browser storage, no page errors.",
  );
} finally {
  await browser?.close();
  vite.kill();
  backend.kill();
}
