"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(path.resolve(__dirname, "../../../node_modules/playwright"));

const config = JSON.parse(fs.readFileSync(0, "utf8"));
const base = new URL(config.base);
assert.ok(base.protocol === "http:" && base.hostname === "127.0.0.1" && base.port && !base.username && !base.password);
const viewports = [["desktop", 1440, 900], ["mobile", 360, 780]];

async function replay() {
  const browser = await chromium.launch({
    channel: process.env.PLAYWRIGHT_CHANNEL || "msedge",
    args: ["--disable-background-networking", "--no-proxy-server"]
  });
  const failures = [];
  const blocked = new Set();
  try {
    for (const [device, width, height] of viewports) {
      const context = await browser.newContext({
        viewport: { width, height }, isMobile: device === "mobile", hasTouch: device === "mobile",
        deviceScaleFactor: 1, locale: "zh-CN", reducedMotion: "reduce", serviceWorkers: "block"
      });
      await context.addCookies([{ ...config.cookie, url: base.origin, httpOnly: true, sameSite: "Lax" }]);
      await context.route("**/*", route => {
        const request = new URL(route.request().url());
        if (request.origin === base.origin) return route.continue();
        blocked.add(request.origin);
        return route.abort();
      });
      const page = await context.newPage();
      page.on("pageerror", error => failures.push(error.message));
      page.on("console", message => {
        if (message.type() === "error") failures.push(message.text());
      });
      page.on("response", response => {
        if (response.status() >= 400) failures.push(`${response.status()} ${new URL(response.url()).pathname}`);
      });

      async function goto(relative) {
        assert.equal((await page.goto(new URL(relative, base).href, { waitUntil: "load" })).status(), 200);
        await page.evaluate(() => document.fonts.ready.then(() => undefined));
      }

      async function screenshot(name, focus) {
        if (focus) {
          await focus.waitFor({ state: "visible" });
          await focus.evaluate(element => element.scrollIntoView({ block: "center", inline: "nearest" }));
          const rect = await focus.boundingBox();
          assert.ok(rect && rect.x >= 0 && rect.x + rect.width <= width, `${name} 的可见区域伸出窗口`);
        }
        const layout = await page.evaluate(() => {
          const root = document.documentElement;
          return { width: root.clientWidth, scroll: Math.max(root.scrollWidth, document.body.scrollWidth) };
        });
        assert.equal(layout.width, width, "浏览器未按设定宽度排版");
        assert.ok(layout.scroll <= width, `${name} 出现横向溢出：${JSON.stringify(layout)}`);
        await page.screenshot({ path: path.join(config.output, `${name}-${device}.png`), animations: "disabled" });
        process.stdout.write(`${name}-${device}.png：${width}×${height}，页面横向滚动宽度 ${layout.scroll}。\n`);
      }

      if (config.stage === "open") {
        await goto(config.sample);
        const registration = page.locator("#regOpenButton");
        const dialog = page.locator("#regOverlay");
        await page.getByText("报名开放中", { exact: true }).waitFor();
        await screenshot("01-open", registration);
        await registration.click();
        await dialog.waitFor();
        assert.equal(await dialog.evaluate(element => element.open), true);
        assert.equal(await page.evaluate(() => document.activeElement?.id), "regTeamName");
        await screenshot("02-registration-dialog", dialog);
        await page.keyboard.press("Escape");
        await dialog.waitFor({ state: "hidden" });
        await page.waitForFunction(() => document.activeElement?.id === "regOpenButton");
        if (device === "mobile") {
          await goto("/events/reserve-practice");
          const reserve = page.locator(".event-substitute-registration");
          assert.equal(await reserve.locator(".event-individual-count").innerText(), "0 人");
          const [response] = await Promise.all([
            page.waitForResponse(item => item.request().method() === "POST" && item.url().endsWith("/register-substitute")),
            reserve.getByRole("button", { name: "报名替补", exact: true }).click()
          ]);
          assert.equal(response.status(), 200);
          assert.equal((await response.json()).success, true);
          await reserve.getByRole("button", { name: "修改替补队伍", exact: true }).waitFor();
          assert.equal(await reserve.locator(".event-individual-count").innerText(), "1 人");
          await screenshot("03-first-reserve", reserve);
        }
      } else if (config.stage === "confirmed") {
        await goto(config.sample);
        await page.getByText("正式报名已截止，仅保留替补报名", { exact: true }).waitFor();
        assert.equal(await page.locator("#regOpenButton").count(), 0);
        assert.equal(await page.locator(".event-reg-team").count(), 2);
        await screenshot("04-cutoff", page.locator(".event-reg-banner"));
        const badges = page.locator(".teams-grid .team-badge");
        assert.equal(await badges.count(), 2);
        assert.deepEqual((await badges.locator(".team-badge-name").allInnerTexts()).sort(), ["个人报名队 1", "青岚"]);
        await screenshot("05-confirmed-teams", page.locator(".teams-grid"));
      } else if (config.stage === "archived") {
        await goto("/events/entrant-practice-old");
        assert.equal(new URL(page.url()).pathname, config.sample);
        assert.equal(await page.locator("#eventRegistrationSection").count(), 0);
        const badges = page.locator(".teams-grid .team-badge");
        assert.equal(await badges.count(), 2);
        const last = badges.last();
        if (device === "desktop") await last.hover();
        else await last.focus();
        const popup = last.locator(".team-players-popup");
        await popup.waitFor({ state: "visible" });
        assert.equal(await popup.locator(".team-player-link").count(), 5);
        const rect = await popup.boundingBox();
        assert.ok(rect && rect.x >= 0 && rect.x + rect.width <= width, "旧名册浮层伸出窗口");
        await screenshot("06-archived-roster", popup);
      } else {
        assert.fail("未知浏览器阶段");
      }
      await context.close();
    }
    assert.deepEqual(failures, [], "浏览器控制台、页面错误或资源加载失败");
    assert.deepEqual([...blocked], [], "页面试图请求非本机来源；请求已阻断");
    process.stdout.write("本阶段：控制台错误、页面例外、资源失败、外部请求均为 0。\n");
  } finally {
    await browser.close();
  }
}

replay().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
