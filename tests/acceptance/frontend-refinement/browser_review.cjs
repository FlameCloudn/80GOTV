"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const f = JSON.parse(fs.readFileSync(0, "utf8"));
const { chromium } = require(f.playwright);
const origin = new URL(f.base).origin;
assert.equal(new URL(origin).hostname, "127.0.0.1");
fs.mkdirSync(f.output, { recursive: true });
const ops = "/admin/matches/" + f.mid + "/operations";
const awards = "/admin/events/" + f.eid + "/operations";
const edit = "/admin/events/edit/" + f.eid;
const operate = "/admin/matches/" + f.mid + "/operate";
const bracket = "/admin/events/" + f.eid + "/bracket";
const signup = "/admin/events/" + f.signup + "/roster";
const opener = '[data-action="open-batch-participation"]';
const screenshots = [], errors = [];

async function capture(page, selector, label) {
  const area = page.locator(selector);
  await area.scrollIntoViewIfNeeded();
  await page.evaluate(() => document.fonts.ready);
  const geometry = await area.evaluate(el => {
    const root = document.documentElement;
    const r = el.getBoundingClientRect();
    const offscreen = [...el.querySelectorAll("button,input,textarea,select")].filter(n => {
      const b = n.getBoundingClientRect();
      return b.width && (b.right > root.clientWidth + 1 || b.left < -1);
    }).map(n => n.id || n.textContent);
    return { width: root.clientWidth, total: root.scrollWidth, left: r.left, right: r.right, offscreen };
  });
  assert(geometry.total <= geometry.width && geometry.left >= -1 && geometry.right <= geometry.width + 1,
    label + "：页面横向溢出 " + JSON.stringify(geometry));
  assert.deepEqual(geometry.offscreen, [], label + "：控件超出屏幕");
  const contrast = await area.evaluate(el => {
    const control = el.querySelector("#linkClubSelect,#newMatchStage,#matchStageInput,#batchPartReason,#managedMvpSelect");
    const style = getComputedStyle(control);
    const light = color => color.match(/[\d.]+/g).slice(0, 3).reduce((sum, c, i) => {
      const v = Number(c) / 255;
      return sum + (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4) * [0.2126,0.7152,0.0722][i];
    }, 0);
    const ratio = (a, b) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const bg = light(style.backgroundColor);
    return { text:ratio(light(style.color), bg), border:ratio(light(style.borderTopColor), bg) };
  });
  assert(contrast.text >= 4.5 && contrast.border >= 3, label + "：输入文字或边界对比度不足 " + JSON.stringify(contrast));
  if (label.includes("-en-")) {
    const leaks = await area.evaluate(el => {
      const found = [], han = /[\u3400-\u9fff]/;
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      for (let n; (n = walker.nextNode());) {
        const p = n.parentElement;
        if (!p.closest("[data-i18n-ignore]") && p.getClientRects().length && han.test(n.textContent))
          found.push(n.textContent.trim());
      }
      for (const n of el.querySelectorAll("[aria-label],[placeholder],[title]")) {
        if (n.closest("[data-i18n-ignore]") || !n.getClientRects().length) continue;
        for (const k of ["title","aria-label","placeholder"])
          if (han.test(n.getAttribute(k) || "")) found.push(n.getAttribute(k));
      }
      return found;
    });
    assert.deepEqual(leaks, [], label + "：英文界面残留中文");
  }
  await area.screenshot({ path: path.join(f.output, label + ".png"), animations: "disabled" });
  screenshots.push(label);
}

async function context(browser, size, lang, theme) {
  const viewport = size === "mobile" ? { width: 390, height: 844 } : { width: 1440, height: 900 };
  const ctx = await browser.newContext({ viewport, colorScheme: theme, locale: lang === "en" ? "en-US" : "zh-CN",
    isMobile: size === "mobile", hasTouch: size === "mobile" });
  await ctx.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
  await ctx.addCookies([{ ...f.cookie, url: origin }]);
  await ctx.addInitScript(([l, t]) => {
    localStorage.setItem("siteLang", l); localStorage.setItem("theme", t);
  }, [lang, theme]);
  const page = await ctx.newPage();
  page.setDefaultTimeout(7000);
  page.on("pageerror", err => errors.push(err.message));
  page.on("console", msg => { if (msg.type() === "error") errors.push(msg.text()); });
  return { ctx, page };
}

async function get(page, url) {
  const resp = await page.request.get(origin + url);
  assert(resp.ok(), url + "：" + resp.status());
  return resp.json();
}

async function formPost(page, button, endpoint) {
  const reply = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname.endsWith(endpoint));
  await page.locator(button).click();
  const response = await reply;
  assert(response.ok(), endpoint + "：" + response.status());
  return response.json();
}

async function matrix(browser, awarded) {
  for (const size of ["desktop","mobile"]) for (const lang of ["zh","en"]) for (const theme of ["light","dark"]) {
    const { ctx, page } = await context(browser, size, lang, theme);
    const label = "-" + size + "-" + lang + "-" + theme;
    try {
      if (awarded) {
        await page.goto(origin + edit + "#managedAwardsPanel");
        await page.waitForSelector("#managedEvpOrderList");
        await capture(page, "#managedAwardsPanel", "awards" + label);
        continue;
      }
      await page.goto(origin + signup);
      assert.equal(await page.locator("html").getAttribute("lang"), lang === "en" ? "en" : "zh-CN");
      assert.equal(await page.locator("html").getAttribute("data-theme"), theme);
      await page.locator('[data-team-name="Northside"]').click();
      await capture(page, "#dialogLinkClub", "club" + label);
      await page.keyboard.press("Escape");
      await page.goto(origin + bracket);
      await page.locator('[data-stage-chip="总决赛"]').click();
      assert.equal(await page.inputValue("#newMatchStage"), lang === "en" ? "Grand final" : "总决赛");
      await capture(page, ".panel:has(#createDownstreamForm)", "bracket" + label);
      await page.goto(origin + "/admin/matches/add?event=" + f.eid);
      assert.equal(await page.inputValue("#eventIdSelect"), String(f.eid));
      await page.locator('[data-match-stage="总决赛"]').focus();
      await page.keyboard.press("Enter");
      assert.equal(await page.inputValue("#matchStageInput"), lang === "en" ? "Grand final" : "总决赛");
      assert(await page.locator("#matchStageInput").evaluate(el => document.activeElement === el));
      assert(await page.locator("#managedFinalHint").isVisible());
      await capture(page, ".form-grid:has(#matchStageInput)", "match" + label);
      await page.goto(origin + operate);
      await page.click(opener);
      await page.check("#batchPartAll");
      await capture(page, "#batchPartDialog", "appearances" + label);
    } finally { await ctx.close(); }
  }
}

async function clubAndNavigation(page) {
  await page.goto(origin + signup);
  const north = page.locator('[data-team-name="Northside"]');
  for (const club of f.clubs) {
    await north.click();
    assert(await page.locator("#linkClubSubmitBtn").isDisabled());
    await page.selectOption("#linkClubSelect", String(club));
    await page.click("#linkClubSubmitBtn");
    await page.waitForSelector('[data-team-name="Northside"][data-club-id="' + club + '"]');
  }
  assert.equal(await page.locator('[data-team-name="Southside"]').getAttribute("data-club-id"), "");
  await north.click();
  assert.equal(await page.inputValue("#linkClubSelect"), String(f.clubs[1]));
  assert(await page.locator("#linkClubSubmitBtn").isDisabled());
  await page.keyboard.press("Escape");
  await page.goto(origin + "/admin/events/" + f.eid + "/roster");
  assert.equal(await page.locator("[data-open-link-club]").count(), 0);
  await page.click('a[href*="/admin/matches/add?event="]');
  assert.equal(await page.inputValue("#eventIdSelect"), String(f.eid));
  assert.equal(await page.locator("#side1_entrant_select option").count(), 3);
  await page.fill("#matchStageInput", "Invitational playoff");
  assert.equal(await page.inputValue("#matchStageInput"), "Invitational playoff");
  await page.goto(origin + bracket);
  await page.locator('.page-actions a[href*="/admin/matches?event="]').click();
  await page.locator('.page-actions a[href*="/admin/matches/add?event="]').click();
  assert.equal(await page.inputValue("#eventIdSelect"), String(f.eid));
  await page.goto(origin + "/admin/matches/add?event=999999");
  assert.equal(await page.inputValue("#eventIdSelect"), "");
}

async function appearances(page) {
  await page.goto(origin + operate);
  await page.click(opener);
  const picks = page.locator("#batchPartPlayerList input");
  assert.equal(await picks.count(), 8);
  assert.equal(await page.locator("#batchPartPlayerList input:checked").count(), 0);
  for (const id of [f.home[0], f.away[0]]) assert.equal(await picks.and(page.locator('[value^="' + id + ':"]')).count(), 0);
  await page.fill("#batchPartReason", "现场核对");
  assert(await page.locator("#batchPartSubmitBtn").isDisabled());
  await page.check("#batchPartAll");
  await picks.last().uncheck();
  assert(await page.locator("#batchPartAll").evaluate(el => el.indeterminate));
  const payloads = [];
  const url = "**" + ops + "/participation";
  await page.route(url, async route => {
    payloads.push(route.request().postDataJSON().player_id);
    if (payloads.length === 2) await route.fulfill({ status: 200, contentType: "text/html", body: "<title>Sign in</title>" });
    else await route.continue();
  });
  await page.click("#batchPartSubmitBtn");
  await page.waitForSelector("#batchPartError:not([hidden])");
  assert.match(await page.innerText("#batchPartError"), /Recorded 1 appearance.*signed in/);
  assert.equal(await page.inputValue("#batchPartReason"), "现场核对");
  assert.equal(await picks.count(), 7);
  assert.equal(await page.locator("#batchPartPlayerList input:checked").count(), 6);
  await page.waitForSelector("#batchPartSubmitBtn:enabled");
  await capture(page, "#batchPartDialog", "appearances-retry-mobile-en-dark");
  await page.click("#batchPartSubmitBtn");
  await page.waitForSelector("#batchPartDialog", {state:"hidden"});
  await page.unroute(url);
  assert.equal(payloads.filter(id => id === payloads[0]).length, 1);
  const panel = await get(page, ops + "/panel-context");
  const records = panel.overview.maps[0].runs[0].participations;
  assert.equal(records.filter(p => p.is_current).length, 8);
  assert.equal(records.find(p => p.player_id === f.away[0]).is_current, 0);
  await page.click('[data-ops-tab="results"]');
  await page.click('[data-action="open-confirm-map"]');
  await page.fill("#confirmMapScore1", "13");
  await page.fill("#confirmMapScore2", "0");
  await formPost(page, '#confirmMapDialog [type="submit"]', "/operations/confirm-map");
  await page.click('[data-action="open-series-settle"]');
  await formPost(page, '#seriesActionDialog [type="submit"]', "/operations/settle");
}

async function grantAwards(page) {
  await page.goto(origin + edit + "#managedAwardsPanel");
  const champ = await get(page, awards + "/championship");
  assert.equal(champ.candidate.players.length, 5);
  await page.waitForSelector("#managedMvpSelect");
  await capture(page, "#managedAwardsPanel", "awards-review-mobile-en-dark");
  await page.click("#awardManagedChampBtn");
  await page.click(".site-modal-cancel");
  assert.equal((await get(page, awards + "/championship")).championship, null);
  await page.click("#awardManagedChampBtn");
  const saved = await formPost(page, ".site-modal-ok", "/operations/championship");
  assert.deepEqual(saved.championship.players.map(p => p.player_id), champ.candidate.players.map(p => p.player_id));
  await page.waitForSelector("#managedChampBadge:text('Awarded')");
  assert.equal(await page.locator(".managed-award-players li").count(), 5);
  for (const p of saved.championship.players) assert((await page.innerText("#managedChampBody")).includes(p.nickname));
  assert.equal(await page.locator("#managedChampBody .field-hint a").getAttribute("href"), operate + "#results");
  await page.selectOption("#managedMvpSelect", String(f.home[0]));
  const evps = f.home.slice(1, 4);
  for (const id of evps) {
    await page.selectOption("#managedEvpAddSelect", String(id));
    await page.click("#managedEvpAddBtn");
  }
  await page.click('[data-evp-remove="' + evps[2] + '"]');
  await page.click('[data-player-id="' + evps[1] + '"] [data-evp-move="up"]');
  const expected = [evps[1],evps[0]];
  const url = "**" + awards + "/player-awards";
  await page.route(url, route => route.fulfill({status:200, contentType:"text/html", body:"<title>Sign in</title>"}));
  await page.click("#saveManagedMedalsBtn");
  await page.waitForSelector("#managedMedalsError:not([hidden])");
  assert.match(await page.innerText("#managedMedalsError"), /signed in/);
  assert.equal(await page.inputValue("#managedMvpSelect"), String(f.home[0]));
  await page.unroute(url);
  assert.deepEqual((await get(page, awards + "/player-awards")).awards, []);
  const result = await formPost(page, "#saveManagedMedalsBtn", "/operations/player-awards");
  assert.deepEqual(result.awards.filter(a => a.type === "EVP").map(a => [a.player_id,a.evp_rank]), expected.map((id,i) => [id,i+1]));
  await page.reload();
  await page.waitForSelector("#managedEvpOrderList");
  assert.deepEqual(await page.locator(".managed-evp-item").evaluateAll(rows => rows.map(row => Number(row.dataset.playerId))), expected);
  assert(await page.locator("#saveManagedMedalsBtn").isDisabled());
  const posters = await page.locator('#managedMedalsBody a[href*="/award-poster/"]').evaluateAll(links => links.map(a => a.href));
  assert.equal(posters.length, 3);
  for (const href of posters) {
    const poster = await page.request.get(href);
    assert(poster.ok() && poster.headers()["content-type"].includes("image/png"), "个人荣誉海报未生成");
  }
  return result.awards;
}

async function changeFinal(page, medals) {
  await page.goto(origin + bracket);
  await page.click('[data-stage-chip="总决赛"]');
  await page.selectOption("#newMatchBo", "BO1");
  const created = await formPost(page, "#createDownstreamBtn", "/operations/bracket");
  await page.waitForSelector('#linkTargetMatch option[value="' + created.match_id + '"]', {state:"attached"});
  const data = await get(page, awards + "/bracket");
  assert.equal(data.matches.find(m => m.id === created.match_id).stage, "Grand final");
  await page.goto(origin + edit + "#managedAwardsPanel");
  await page.waitForSelector("#managedChampBadge:text('Needs review')");
  assert.equal(await page.locator(".managed-award-players li").count(), 5);
  assert.equal(await page.locator("#awardManagedChampBtn").count(), 0);
  await page.waitForSelector(".managed-saved-medals");
  assert.deepEqual(await page.locator(".managed-saved-medals a").allTextContents(), medals.map(a => a.nickname));
  assert.equal(await page.locator("#saveManagedMedalsBtn").count(), 0);
}

(async () => {
  const browser = await chromium.launch({ channel:"msedge", headless:true });
  try {
    await matrix(browser, false);
    const { ctx, page } = await context(browser, "mobile", "en", "dark");
    try {
      await clubAndNavigation(page);
      await page.goto(origin + edit);
      await page.waitForSelector("#managedChampBody:text('not been officially settled')");
      assert.equal(await page.locator("#awardManagedChampBtn").count(), 0);
      await appearances(page);
      const medals = await grantAwards(page);
      await matrix(browser, true);
      await changeFinal(page, medals);
    } finally { await ctx.close(); }
    assert.deepEqual(errors, [], "浏览器控制台或脚本报错");
    console.log("报名、阶段、批量出场、团队冠军及 MVP/EVP 验收通过；已检查 " + screenshots.length + " 张截图。");
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
