"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { strict: assert } = require("node:assert");
const fixture = JSON.parse(fs.readFileSync(0, "utf8"));
const { chromium } = require(fixture.playwright);
const origin = new URL(fixture.base).origin;
assert.equal(new URL(origin).hostname, "127.0.0.1");
fs.mkdirSync(fixture.output, { recursive: true });

(async () => {
  const browser = await chromium.launch({ channel: "msedge", args: ["--disable-background-networking", "--no-proxy-server"] });
  const findings = [];
  try {
    for (const [device, width, height] of [["desktop", 1440, 900], ["mobile", 390, 844]]) {
      for (const theme of ["light", "dark"]) {
        const context = await browser.newContext({
          viewport: { width, height }, isMobile: device === "mobile", hasTouch: device === "mobile",
          locale: "zh-CN", reducedMotion: "reduce", serviceWorkers: "block",
        });
        await context.addInitScript(value => localStorage.setItem("theme", value), theme);
        await context.addCookies([{ ...fixture.cookie, url: origin, httpOnly: true, sameSite: "Lax" }]);
        await context.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
        const page = await context.newPage();
        const pages = fixture.mode === "completed" ? [
          ["completed-results", "/results", "远岸"],
          ["completed-match", fixture.managed_match, "远岸"],
          ...Object.entries(fixture.players).map(([label, player]) => [`completed-${label}`, player.url, player.name]),
        ] : [
          ["managed-match", fixture.managed_match, "远岸"],
          ["admin-match", fixture.admin_match, "本场阵容"],
          ["legacy-results", "/results", "旧届海岸队"],
          ["legacy-match", fixture.legacy_match, "旧届海岸队"],
          ["legacy-player", fixture.legacy_player, "旧届验收选手"],
        ];
        for (const [name, url, expected] of pages) {
          const failed = new Set(), errors = [];
          const responseError = response => { if (response.status() >= 400) failed.add(new URL(response.url()).pathname); };
          const requestError = request => { if (new URL(request.url()).origin === origin) failed.add(new URL(request.url()).pathname); };
          const pageError = error => errors.push(error.message);
          const consoleError = msg => { if (msg.type() === "error") errors.push(msg.text()); };
          page.on("response", responseError); page.on("requestfailed", requestError);
          page.on("pageerror", pageError); page.on("console", consoleError);
          const response = await page.goto(origin + url, { waitUntil: "load" });
          await page.evaluate(() => document.fonts.ready);
          const text = await page.locator("body").innerText();
          if (name === "admin-match") {
            await page.getByRole("button", { name: /本场阵容/ }).click();
            assert.equal(await page.locator("#pane-roster").isVisible(), true);
          }
          await page.keyboard.press("Tab");
          const sizes = await page.evaluate(() => ({
            width: document.documentElement.clientWidth,
            scroll: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
          }));
          const file = `${name}-${device}-${theme}.png`;
          await page.screenshot({ path: path.join(fixture.output, file), fullPage: true, animations: "disabled" });
          const result = { name, device, theme, status: response.status(), contains_expected: text.includes(expected),
            ...sizes, failed: [...failed], errors, file };
          findings.push(result);
          page.off("response", responseError); page.off("requestfailed", requestError);
          page.off("pageerror", pageError); page.off("console", consoleError);
        }
        if (fixture.mode !== "completed") {
          await page.goto(origin + "/results", { waitUntil: "load" });
          await page.locator(".result-row").filter({ hasText: "旧届海岸队" }).click();
          await page.waitForURL(origin + fixture.legacy_match);
          await page.locator(`a[href="${fixture.legacy_player}"]`).first().click();
          await page.waitForURL(origin + fixture.legacy_player);
          assert.ok((await page.locator("body").innerText()).includes("旧届验收选手"));
          if (theme === "light") {
            await context.clearCookies();
            await context.addCookies([{ ...fixture.voters[device], url: origin, httpOnly: true, sameSite: "Lax" }]);
            await page.goto(origin + fixture.managed_match, { waitUntil: "load" });
            await page.locator("#score1").fill("2");
            await page.locator("#score2").fill("1");
            const [receipt] = await Promise.all([
              page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname.endsWith("/vote")),
              page.locator('[data-vote="t1"]').click(),
            ]);
            assert.equal(receipt.status(), 200);
            await page.locator(".vote-voted-hint").waitFor();
            await page.screenshot({ path: path.join(fixture.output, `vote-${device}-light.png`), fullPage: true, animations: "disabled" });
          }
        }
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify(findings, null, 2) + "\n");
  if (findings.some(item => item.status !== 200 || !item.contains_expected || item.scroll > item.width || item.failed.length || item.errors.length)) {
    process.exitCode = 1;
  }
})().catch(error => { process.stderr.write(`${error.stack || error}\n`); process.exitCode = 1; });
