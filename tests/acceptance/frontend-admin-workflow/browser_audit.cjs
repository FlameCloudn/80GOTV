"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { strict: assert } = require("node:assert");
const fixture = JSON.parse(fs.readFileSync(0, "utf8"));
const { chromium } = require(fixture.playwright);
const origin = new URL(fixture.base).origin;
assert.equal(new URL(origin).hostname, "127.0.0.1");
fs.mkdirSync(fixture.output, { recursive: true });

async function auditPage(page, name, url, device, theme, expectedTexts, interact) {
  const failed = new Set();
  const errors = [];
  const onResponse = r => { if (r.status() >= 400) failed.add(new URL(r.url()).pathname + ":" + r.status()); };
  const onReqFail = req => { if (new URL(req.url()).origin === origin) failed.add(new URL(req.url()).pathname); };
  const onPageErr = err => errors.push(err.message);
  const onConsole = msg => { if (msg.type() === "error") errors.push(msg.text()); };
  page.on("response", onResponse);
  page.on("requestfailed", onReqFail);
  page.on("pageerror", onPageErr);
  page.on("console", onConsole);

  const resp = await page.goto(origin + url, { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);
  if (interact) await interact(page);
  const bodyText = await page.locator("body").innerText();
  const missingTexts = (expectedTexts || []).filter(t => !bodyText.includes(t));
  await page.keyboard.press("Tab");
  const sizes = await page.evaluate(() => ({
    width: document.documentElement.clientWidth,
    scroll: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
  }));
  const file = `${name}-${device}-${theme}.png`;
  await page.screenshot({ path: path.join(fixture.output, file), fullPage: true, animations: "disabled" });

  page.off("response", onResponse);
  page.off("requestfailed", onReqFail);
  page.off("pageerror", onPageErr);
  page.off("console", onConsole);
  return {
    name, device, theme, status: resp ? resp.status() : null,
    missingTexts, ...sizes,
    overflow: sizes.scroll > sizes.width,
    failed: [...failed], errors, file,
  };
}

(async () => {
  const browser = await chromium.launch({
    channel: "msedge",
    args: ["--disable-background-networking", "--no-proxy-server"],
  });
  const results = [];
  try {
    // 1. Desktop interactive flow + screenshots (light & dark)
    for (const [device, width, height] of [["desktop", 1440, 900], ["mobile", 390, 844]]) {
      for (const theme of ["light", "dark"]) {
        const ctx = await browser.newContext({
          viewport: { width, height },
          isMobile: device === "mobile",
          hasTouch: device === "mobile",
          locale: "zh-CN",
          reducedMotion: "reduce",
          serviceWorkers: "block",
        });
        await ctx.addInitScript(t => localStorage.setItem("theme", t), theme);
        await ctx.addCookies([{ ...fixture.cookie, url: origin, httpOnly: true, sameSite: "Lax" }]);
        await ctx.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
        const page = await ctx.newPage();

        results.push(await auditPage(page, "admin-events-list", "/admin/events", device, theme, ["新流程春季杯", "报名与阵容"]));
        results.push(await auditPage(page, "admin-events-add", "/admin/events/add", device, theme, ["新报名管理"], async p => {
          await p.locator('input[name="registration_mode"][value="managed"]').check();
          assert.equal(await p.locator("#managedAddDeadlineWrap").isVisible(), true);
        }));
        results.push(await auditPage(page, "admin-events-edit-blocked", `/admin/events/edit/${fixture.legacy_eid}`, device, theme, ["这届赛事不能改用新报名管理，原因："]));
        results.push(await auditPage(page, "admin-roster-formed", `/admin/events/${fixture.eid_b}/roster`, device, theme, [
          "超级长参赛队伍名称", "本届初始五人", "当前阵容", "换入", "已换出", "保留初始 4 / 5", "候补测试队员25",
        ]));
        results.push(await auditPage(page, "admin-match-add", "/admin/matches/add", device, theme, ["本届参赛队"], async p => {
          await p.selectOption("#eventIdSelect", String(fixture.eid_b));
          await p.waitForSelector("#side1_entrant_select:not([disabled])");
          const opts = await p.locator("#side1_entrant_select option").allTextContents();
          assert.ok(opts.some(t => t.includes("可建场")));
          const val1 = await p.locator("#side1_entrant_select option:nth-child(2)").getAttribute("value");
          const val2 = await p.locator("#side1_entrant_select option:nth-child(3)").getAttribute("value");
          await p.selectOption("#side1_entrant_select", val1);
          await p.selectOption("#side2_entrant_select", val2);
          await p.locator("#side1_entrant_preview .player-tag").first().waitFor();
        }));
        results.push(await auditPage(page, "admin-match-edit-roster", `/admin/matches/edit/${fixture.mid_b}`, device, theme, [
          "本场阵容", "本届初始五人", "本届当前阵容", "本场冻结阵容", "冻结只记录本场参赛名单，不表示选手已到场或比赛已开始",
        ], async p => {
          await p.getByRole("button", { name: /本场阵容/ }).click();
          assert.equal(await p.locator("#pane-roster").isVisible(), true);
        }));
        results.push(await auditPage(page, "admin-matches-list", "/admin/matches", device, theme, ["本场阵容未冻结"]));
        results.push(await auditPage(page, "match-detail-prediction", `/matches/${fixture.mid_closed}`, device, theme, [
          "本场对阵未确定或已停止接受竞猜，暂不开放赛前预测。",
        ]));
        results.push(await auditPage(page, "predictions-list", "/predictions", device, theme, ["往届传统杯"]));

        await ctx.close();
      }
    }

    // 2. Interactive UI click-through on Event A (preform -> claim -> release -> form-due) + freeze M_b on desktop light
    const ctx = await browser.newContext({
      viewport: { width: 1440, height: 900 }, locale: "zh-CN", reducedMotion: "reduce", serviceWorkers: "block",
    });
    await ctx.addInitScript(() => localStorage.setItem("theme", "light"));
    await ctx.addCookies([{ ...fixture.cookie, url: origin, httpOnly: true, sameSite: "Lax" }]);
    await ctx.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    const page = await ctx.newPage();

    results.push(await auditPage(page, "admin-roster-preform", `/admin/events/${fixture.eid_a}/roster`, "desktop", "light", [
      "分队前检查", "待核实预留位", "预留老四", "待释放占坑", "@u3",
    ]));

    // Click claim on slot 3
    await page.locator('[data-open-review="claim"]').first().click();
    await page.fill("#reviewReasonInput", "浏览器实点核实认领");
    await Promise.all([
      page.waitForNavigation({ waitUntil: "load" }),
      page.click("#reviewSubmitBtn"),
    ]);

    // Click release on slot 4
    await page.locator('[data-open-review="release"]').first().click();
    await page.fill("#reviewReasonInput", "浏览器实点释放空位");
    await Promise.all([
      page.waitForNavigation({ waitUntil: "load" }),
      page.click("#reviewSubmitBtn"),
    ]);

    // Click form-due -> confirm modal -> wait reload -> verify formed teams appear!
    await page.click("#formDueBtn");
    await page.locator(".site-modal-ok").click();
    await page.waitForNavigation({ waitUntil: "load" });
    const afterFormText = await page.locator("body").innerText();
    assert.ok(afterFormText.includes("已分队 · 首五待确认"), "Expected formed state after clicking form-due");

    // Freeze Match B via UI button & confirm modal -> verify frozen state
    await page.goto(origin + `/admin/matches/edit/${fixture.mid_b}`, { waitUntil: "load" });
    await page.getByRole("button", { name: /本场阵容/ }).click();
    await page.click("#freezeMatchRostersBtn");
    await page.locator(".site-modal-ok").click();
    await page.waitForNavigation({ waitUntil: "load" });
    await page.goto("about:blank");
    results.push(await auditPage(page, "admin-match-edit-frozen", `/admin/matches/edit/${fixture.mid_b}#pane-roster`, "desktop", "light", [
      "本场阵容已冻结", "只读 · 已冻结", "本场双方十人已记录为只读状态",
    ]));

    await ctx.close();
  } finally {
    await browser.close();
  }

  fs.writeFileSync(path.join(fixture.output, "audit.json"), JSON.stringify(results, null, 2));
  process.stdout.write(JSON.stringify(results, null, 2) + "\n");
  if (results.some(r => r.status !== 200 || r.missingTexts.length || r.overflow || r.failed.length || r.errors.length)) {
    process.exitCode = 1;
  }
})().catch(err => {
  process.stderr.write(`${err.stack || err}\n`);
  process.exitCode = 1;
});
