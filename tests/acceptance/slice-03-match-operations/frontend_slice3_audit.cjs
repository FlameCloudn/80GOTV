"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { strict: assert } = require("node:assert");
const fixture = JSON.parse(fs.readFileSync(0, "utf8"));
const { chromium } = require(fixture.playwright);
const origin = new URL(fixture.base).origin;
assert.equal(new URL(origin).hostname, "127.0.0.1");
fs.mkdirSync(fixture.output, { recursive: true });

const IGNORED_SELECTOR = [
  ".news-title", ".news-summary", ".comment-content", ".comment-body",
  ".comment-author", ".comment-avatar-fb", ".username",
  ".team", ".team-name", ".player-name", ".player-link", ".sidebar-event-name",
  ".bp-player-name", ".sd-label", ".sd-sub", ".overview-mini-tag", ".overview-team-mark",
  ".overview-rank-name", ".award-event-name", ".award-champ-team", ".award-medal-player",
  ".award-medal-team", ".overview-avatar-fallback", ".profile-trophy span",
  ".profile-achievement-list span", ".profile-match-row small",
  "[data-i18n-ignore]", "[contenteditable=\"true\"]",
].join(",");

async function collectCjkLeaks(page) {
  return page.evaluate(({ ignoredSel }) => {
    const leaks = [];
    const cjk = /[\u3400-\u9fff\uf900-\ufaff]/;
    const isHidden = (el) => {
      if (!el || el.closest("dialog:not([open])")) return true;
      const st = getComputedStyle(el);
      return st.display === "none" || st.visibility === "hidden";
    };
    const isIgnoredEl = (el) => Boolean(el && el.closest(ignoredSel));
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      const val = (n.nodeValue || "").trim();
      if (!val || !cjk.test(val)) continue;
      const p = n.parentElement;
      if (!p || /^(SCRIPT|STYLE|TEXTAREA|NOSCRIPT)$/.test(p.tagName)) continue;
      if (isIgnoredEl(p) || isHidden(p)) continue;
      if (p.closest("#languageSelect") && val === "中文") continue;
      leaks.push({ tag: p.tagName.toLowerCase(), cls: p.className || "", text: val.slice(0, 120) });
    }
    for (const el of document.querySelectorAll("[placeholder], [title], [aria-label]")) {
      if (isIgnoredEl(el) || isHidden(el)) continue;
      for (const attr of ["placeholder", "title", "aria-label"]) {
        const av = (el.getAttribute(attr) || "").trim();
        if (av && cjk.test(av)) {
          leaks.push({ tag: el.tagName.toLowerCase(), attr, cls: el.className || "", text: av.slice(0, 120) });
        }
      }
    }
    return leaks.slice(0, 30);
  }, { ignoredSel: IGNORED_SELECTOR });
}

async function checkLayout(page, label, fileName, checkEnLeaks) {
  await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
  const sizes = await page.evaluate(() => ({
    width: document.documentElement.clientWidth,
    scroll: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
  }));
  const leaks = checkEnLeaks ? await collectCjkLeaks(page) : [];
  if (await page.locator(".ops-stat-input").first().isVisible()) {
    const contrast = await page.evaluate(() => {
      const luminance = color => color.match(/[\d.]+/g).slice(0, 3).map(c => {
        const v = Number(c) / 255;
        return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
      }).reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
      const ratio = (a, b) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      const button = getComputedStyle(document.querySelector(".ops-scope-toggle .active"));
      const input = getComputedStyle(document.querySelector(".ops-stat-input"));
      return [ratio(luminance(button.color), luminance(button.backgroundColor)),
        ratio(luminance(input.borderTopColor), luminance(input.backgroundColor))];
    });
    assert(contrast[0] >= 4.5 && contrast[1] >= 3, label + "：统计切换文字或输入框边界对比度不足：" + contrast);
  }
  if (fileName) {
    await page.screenshot({
      path: path.join(fixture.output, fileName),
      fullPage: !fileName.startsWith("retention-") && !fileName.includes("mobile-dark"),
      animations: "disabled",
    });
  }
  return {
    label,
    file: fileName || null,
    width: sizes.width,
    scroll: sizes.scroll,
    overflow: sizes.scroll > sizes.width,
    cjkLeaks: leaks,
  };
}

async function newAdminPage(browser, { width, height, lang, theme }) {
  const ctx = await browser.newContext({ viewport: { width, height } });
  await ctx.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
  await ctx.addCookies([{ name: fixture.cookie.name, value: fixture.cookie.value, url: origin }]);
  await ctx.addInitScript(({ l, t }) => {
    localStorage.setItem("siteLang", l);
    localStorage.setItem("theme", t);
  }, { l: lang, t: theme });
  const page = await ctx.newPage();
  const errors = [];
  const failed = [];
  page.on("pageerror", err => errors.push("pageerror: " + err.message));
  page.on("console", msg => {
    if (msg.type() === "error" && !msg.text().includes("404 (NOT FOUND)")) errors.push("console: " + msg.text());
  });
  page.on("response", r => {
    if (r.status() >= 400 && !r.url().includes("/api/live/")) {
      failed.push(new URL(r.url()).pathname + ":" + r.status());
    }
  });
  return { ctx, page, errors, failed };
}

async function submitted(page, button, suffix) {
  const [response] = await Promise.all([
    page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname.endsWith(suffix), {timeout: 320000}),
    page.locator(button).click(),
  ]);
  const body = await response.json();
  assert(response.ok() && body.ok, body.error || ("提交失败：" + suffix));
  return body;
}

async function postJson(page, url, data) {
  const token = await page.locator('meta[name="csrf-token"]').getAttribute("content");
  const response = await page.request.post(origin + url, {data, headers: {"X-CSRF-Token": token}});
  const body = await response.json();
  assert(response.ok() && body.ok, body.error || ("请求失败：" + url));
  return body;
}

async function playFinal(page, report) {
  const id = fixture.target_mid;
  const ops = `/admin/matches/${id}/operations`;
  const overview = async () => (await page.request.get(origin + ops + "/panel-context")).json();
  await page.goto(origin + `/admin/matches/${id}/operate`);
  const token = await page.locator('meta[name="csrf-token"]').getAttribute("content");
  const freeze = await page.request.post(origin + `/admin/matches/${id}/freeze-rosters`, {headers: {"X-CSRF-Token": token}, maxRedirects: 0});
  assert.equal(freeze.status(), 302);
  const veto = `/api/bp/${id}`;
  let state;
  const step = async (action, team = "t1", extra = {}) => {
    state = (await postJson(page, veto + "/action", {action, team, bp_revision: state?.revision, ...extra})).state;
  };
  await step("start");
  do { await step("roll"); await step("roll", "t2"); } while (state.status === "rolling");
  await step("choose_order", state.first_picker, {choice: "first"});
  while (state.status === "bp") {
    const { info } = await (await page.request.get(origin + veto + "/state")).json();
    await step("ban", info.team, {map: state.pool[0]});
  }
  for (const p of state.picks) if (p.side == null) await step("choose_side", p.side_team, {map: p.map, side: "CT"});
  assert.equal(state.status, "completed");
  await page.reload();
  assert.equal((await overview()).overview.maps[0].runs.length, 0);
  await page.click("#opsAuthorizeBtn");
  await page.click(".site-modal-cancel");
  assert.equal((await overview()).overview.authorized, false);
  await page.click("#opsAuthorizeBtn");
  await submitted(page, ".site-modal-ok", "/authorize");
  await page.click('[data-action="open-start-run"]');
  await page.fill("#startRunEvidence", "现场核对开打");
  const first = await submitted(page, "#startRunSubmitBtn", "/start");
  await page.click('[data-action="bind-director"]');
  await page.fill("#bindDirectorSessionId", "qa-final-first");
  await page.fill("#bindDirectorReason", "核对会话");
  await submitted(page, "#bindDirectorForm [type=submit]", "/bind-director-session");
  const feed = "**/api/live/" + id;
  let frame = {ok:true, source:"gsi", map_run_id:first.map_run_id, team1:{score:0}, team2:{score:null}};
  await page.route(feed, route => route.fulfill({json:frame}));
  await page.click('[data-ops-tab="results"]');
  const live = page.locator("[data-live-run] strong");
  await live.filter({hasText:"0 : -"}).waitFor();
  frame = {...frame, map_run_id: first.map_run_id + 1, team1:{score:9}};
  await page.waitForFunction(() => document.querySelector("[data-live-run] strong")?.textContent === "-");
  frame = {ok:false, reason:"map_run_void"};
  await page.waitForSelector('[data-live-run] small:text("原局已作废，等待新局")');
  await page.unroute(feed);
  await page.click('[data-ops-tab="runs"]');
  let snap = await overview();
  const home = snap.context.participants.find(p => p.side_key === "home");
  const outgoing = home.players[0].id;
  const incoming = home.assigned_reserves[0].player_id;
  await page.click('[data-action="open-tech-replay"]');
  await page.fill("#techReplayReason", "无法恢复原局，现场确认替换");
  await page.check("#techReplaySubToggle");
  await page.selectOption("#techReplayOutgoing", String(outgoing));
  await page.selectOption("#techReplayIncoming", String(incoming));
  const official = snap.overview.results.maps[0];
  await postJson(page, ops + "/confirm-map", {scheduled_map_id:official.scheduled_map_id, map_run_id:first.map_run_id,
    score1:13, score2:9, expected_revision:official.revision, reason:"另一位管理员先记录了原局图分"});
  const oldRun = page.waitForResponse(r => r.url().endsWith("/technical-replay") && r.status() === 409);
  await page.click("#techReplaySubmitBtn");
  await oldRun;
  await page.click("#techReplayReload");
  await page.waitForFunction(() => document.querySelector("#techReplayContext").textContent.includes("13 : 9"));
  assert.equal(await page.inputValue("#techReplayReason"),"无法恢复原局，现场确认替换");
  assert.equal(await page.inputValue("#techReplayIncoming"),String(incoming));
  const voided = await submitted(page, "#techReplaySubmitBtn", "/technical-replay");
  assert.equal(voided.void_map_run_id, first.map_run_id);
  await page.click(`[data-prev-run-id="${first.map_run_id}"]`);
  await page.fill("#startRunEvidence", "重赛首回合已开打");
  const replay = await submitted(page, "#startRunSubmitBtn", "/start");
  assert.notEqual(replay.map_run_id, first.map_run_id);
  await page.click('[data-action="bind-director"]');
  await page.fill("#bindDirectorSessionId", "qa-final-replay");
  await page.fill("#bindDirectorReason", "核对重赛独立会话");
  await submitted(page, "#bindDirectorForm [type=submit]", "/bind-director-session");
  snap = await overview();
  const run = snap.overview.maps[0].runs.find(r => r.map_run_id === replay.map_run_id);
  assert.equal(run.previous_map_run_id, first.map_run_id);
  assert.equal(run.participations.length, 0);
  for (const member of run.lineup.filter(p => p.match_participant_id === home.match_participant_id)) {
    await page.click(`[data-action="quick-participation"][data-run-id="${run.map_run_id}"][data-player-id="${member.player_id}"]`);
    await page.fill("#recordPartReason", "核对重赛实际出场");
    const part = await submitted(page, "#recordPartForm [type=submit]", "/participation");
    if (member.player_id === incoming) {
      for (const present of ["0", "1"]) {
        await page.click(`[data-action="review-participation"][data-part-id="${part.participation_id}"][data-present="${present}"]`);
        await page.fill("#reviewPartReason", "现场重新核对");
        await submitted(page, "#reviewPartSubmitBtn", "/review-participation");
      }
    }
  }
  await page.click('[data-ops-tab="results"]');
  await page.click('[data-action="open-confirm-map"]');
  await page.fill("#confirmMapScore1", "13");
  await page.fill("#confirmMapScore2", "0");
  await submitted(page, "#confirmMapForm [type=submit]", "/confirm-map");
  assert.equal((await overview()).overview.results.series, null);
  await page.click('[data-action="open-series-settle"]');
  await submitted(page, "#seriesActionSubmitBtn", "/settle");
  const awardPath = `/admin/events/${fixture.eid}/operations/championship`;
  const {candidate} = await (await page.request.get(origin + awardPath)).json();
  assert.equal(candidate.match_id, id);
  assert(candidate.players.some(p => p.player_id === incoming));
  await postJson(page, awardPath, {match_id: id, settlement_id: candidate.settlement_id, player_ids: candidate.players.map(p => p.player_id)});
  await page.goto(origin + "/awards");
  const champion = page.locator("a.award-champion", {hasText: home.name});
  assert((await champion.getAttribute("href")).startsWith("/events/"));
  report.push(await checkLayout(page, "临时队冠军", "awards-temp-team.png", false));
  await champion.focus();
  await page.keyboard.press("Enter");
  await page.waitForURL("**/events/*");
  await page.goto(origin + "/players/" + incoming);
  assert(await page.locator(".player-coverage").isVisible());
  report.push(await checkLayout(page, "选手覆盖范围", "player-coverage.png", false));
}

(async () => {
  const browser = await chromium.launch({
    channel: "msedge",
    args: ["--disable-background-networking", "--no-proxy-server"],
  });
  const report = [];
  let fatal = false;

  try {
    // 0. Public Live Page (while match is still 'live'): verify null vs 0 AND map_run_void clearing!
    const liveCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await liveCtx.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    await liveCtx.addInitScript(() => {
      localStorage.setItem("siteLang", "zh");
      localStorage.setItem("theme", "dark");
    });
    const livePage = await liveCtx.newPage();
    try {
      let livePhase = "active";
      await livePage.route(`**/api/live/${fixture.mid}`, async route => {
        if (livePhase === "active") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              ok: true,
              map_run_id: 101,
              source: "gsi",
              map_name: "de_mirage",
              round: 6,
              timer: "1:22",
              team1: { name: "Alpha", side: "CT", score: 4 },
              team2: { name: "Bravo", side: "T", score: 2 },
              players_t1: [
                { name: "ZeroKills", hp: 100, armor: 100, helmet: true, money: 0, kills: 0, assists: null, deaths: 3, adr: null, alive: true },
                { name: "UnknownHp", hp: null, armor: 0, helmet: false, money: null, kills: null, assists: 0, deaths: null, adr: 0, alive: false }
              ],
              players_t2: [
                { name: "Opponent1", hp: 75, armor: 80, helmet: false, money: 4100, kills: 5, assists: 1, deaths: 2, adr: 88, alive: true }
              ],
              round_history: [
                { round_number: 1, winner: "t1", side: "ct", reason_code: "elimination", score_ct: null, score_t: null }
              ],
              overtime_history: [],
              updated_at: new Date().toISOString()
            })
          });
        } else if (livePhase === "void") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ ok: false, reason: "map_run_void" })
          });
        } else {
          await route.fulfill({json: {ok:true, map_run_id:livePhase === "replay" ? 102 : 103, source:"gsi",
            map_name:"de_mirage", team1:{name:"Alpha",score:0}, team2:{name:"Bravo",score:null},
            round_history:livePhase === "replay" ? [{round_number:1,side:"t",winner:"t2",score_ct:0,score_t:1}] : []}});
        }
      });

      await livePage.goto(`${origin}/matches/${fixture.match_slug}`, { waitUntil: "load" });
      await livePage.waitForFunction(() => document.getElementById("liveScore1")?.textContent === "4");
      const activeCheck = await livePage.evaluate(() => {
        const rows = Array.from(document.querySelectorAll("#team1Players .player-row"));
        const readRow = r => ({
          nick: r.querySelector(".p-nick")?.textContent,
          hp: r.querySelector(".hp-num")?.textContent,
          money: r.querySelector(".p-money")?.textContent,
          k: r.querySelector(".p-stat.k")?.textContent,
          a: r.querySelector(".p-stat.a")?.textContent,
          d: r.querySelector(".p-stat.d")?.textContent,
          adr: r.querySelector(".p-adr")?.textContent,
        });
        return {
          r0: readRow(rows[0]),
          r1: readRow(rows[1]),
          feed: document.getElementById("killFeed")?.innerText || "",
        };
      });
      assert.deepEqual(activeCheck.r0, { nick: "ZeroKills", hp: "100", money: "$0", k: "0", a: "-", d: "3", adr: "-" });
      assert.deepEqual(activeCheck.r1, { nick: "UnknownHp", hp: "-", money: "-", k: "-", a: "0", d: "-", adr: "0" });
      assert(!activeCheck.feed.includes("(0 - 0)"), "Unknown round side scores must not render as (0 - 0)");
      report.push(await checkLayout(livePage, "live-null-vs-zero-desktop", "live-null-vs-zero-desktop.png", false));

      // Now trigger map_run_void on next poll (1s interval)
      livePhase = "void";
      await livePage.waitForFunction(() => {
        const badge = document.getElementById("sourceBadge")?.textContent || "";
        return badge.includes("技术重赛作废");
      }, { timeout: 5000 });
      const voidCheck = await livePage.evaluate(() => ({
        s1: document.getElementById("liveScore1")?.textContent,
        s2: document.getElementById("liveScore2")?.textContent,
        badge: document.getElementById("sourceBadge")?.textContent,
        firstNick: document.querySelector("#team1Players .player-row .p-nick")?.textContent,
        firstK: document.querySelector("#team1Players .player-row .p-stat.k")?.textContent,
      }));
      assert.equal(voidCheck.s1, "-", "Void run must clear live score 1");
      assert.equal(voidCheck.s2, "-", "Void run must clear live score 2");
      assert.equal(voidCheck.firstNick, "-", "Void run must clear stale players");
      assert.equal(voidCheck.firstK, "-", "Void run must clear player stats to '-'");
      report.push(await checkLayout(livePage, "live-void-cleared-desktop", "live-void-cleared-desktop.png", false));
      assert.equal(await livePage.locator("#killFeed [data-event-id]").count(), 0);
      livePhase = "replay";
      await livePage.waitForFunction(() => document.querySelector("#killFeed")?.innerText.includes("(0 - 1)"));
      assert.equal(await livePage.locator("#liveScore1").textContent(), "0");
      assert.equal(await livePage.locator("#liveScore2").textContent(), "-");
      livePhase = "next";
      await livePage.waitForFunction(() => document.querySelectorAll("#killFeed [data-event-id]").length === 0);
      assert(!(await livePage.locator("#sourceBadge").innerText()).includes("作废"));
    } finally {
      await liveCtx.close();
    }

    // 1. Desktop Light ZH — full interactive walkthrough across all 4 tabs + managed bracket
    const dLight = await newAdminPage(browser, { width: 1440, height: 900, lang: "zh", theme: "light" });
    try {
      await dLight.page.goto(`${origin}/admin/matches/${fixture.mid}/operate`, { waitUntil: "load" });
      await dLight.page.evaluate(() => document.fonts.ready);

      // Tab 1: Start & Map Runs (with void run + technical substitute visible!)
      const runsText = await dLight.page.locator("body").innerText();
      assert(runsText.includes("已授权可开赛"), "Expected authorized status");
      assert(runsText.includes("技术重赛作废记录"), "Expected technical rematch void record");
      assert(runsText.includes("技术替补"), "Expected carried-over technical substitute badge");
      report.push(await checkLayout(dLight.page, "ops-runs-desktop-light", "ops-runs-desktop-light.png", false));

      const bracketPage = await dLight.ctx.newPage();
      await bracketPage.goto(origin + `/admin/events/${fixture.eid}/bracket`);
      await bracketPage.selectOption("#linkSourceMatch", String(fixture.mid));
      await bracketPage.selectOption("#linkOutcome", "loser");
      await bracketPage.selectOption("#linkTargetMatch", String(fixture.target_mid));
      await bracketPage.selectOption("#linkTargetSide", "away");
      await submitted(bracketPage, "#configLinkBtn", "/bracket-link");
      await bracketPage.waitForFunction(() => document.querySelectorAll("#managedLinksContainer tbody tr").length === 2);
      await bracketPage.close();

      // Tab 2: Demos & Analysis Preview
      await dLight.page.click('[data-ops-tab="demos"]');
      await dLight.page.click(`[data-action="toggle-analyses"][data-demo-id="${fixture.demo1_id}"]`);
      await dLight.page.waitForSelector(`[data-action="preview-analysis"][data-analysis-id="${fixture.analysis_id}"]`);
      await dLight.page.click(`[data-action="preview-analysis"][data-analysis-id="${fixture.analysis_id}"]`);
      await dLight.page.waitForSelector("#opsDemoPreviewPanel:not([hidden])");
      const previewText = await dLight.page.locator("#opsDemoPreviewBody").innerText();
      assert(previewText.includes("冲突覆盖"), "Expected conflict replacement badge in demo preview");
      assert(previewText.includes("19 → 20"), "Expected kills conflict diff 19 -> 20 in demo preview");
      assert(previewText.includes("13 : 8"), "Expected candidate score in demo preview");
      report.push(await checkLayout(dLight.page, "ops-demos-desktop-light", "ops-demos-desktop-light.png", false));
      const field = dLight.page.locator('.ops-adopt-player-card').filter({hasText:"19 → 20"}).locator('[data-scope="ct"][data-field="kills"]');
      const readField = async (id, scope) => (await dLight.page.request.get(origin + `/admin/matches/${fixture.mid}/operations/runs/${fixture.r1}/players/${id}/stats?scope=${scope}&history=1`)).json();
      await field.check();
      await dLight.page.fill("#demoAdoptReason", "仅采纳 CT 击杀，保留整图人工记录");
      await dLight.page.check("#demoDownloadDefaultCb");
      await postJson(dLight.page, `/admin/matches/${fixture.mid}/operations/stats`, {map_run_id:fixture.r1, player_id:fixture.first_pid,
        scope:"ct", fields:{kills:2}, expected_revision:(await readField(fixture.first_pid,"ct")).revision, reason:"现场先收到 CT 方订正"});
      const oldDiff = dLight.page.waitForResponse(r => r.url().endsWith("/api/demos/adopt") && r.status() === 409);
      await dLight.page.click("#demoAdoptSubmitBtn");
      await oldDiff;
      assert.equal((await readField(fixture.first_pid,"ct")).fields.kills, 2);
      await dLight.page.click("#demoReviewLatest");
      await dLight.page.waitForFunction(() => document.querySelector("#opsDemoPreviewBody").innerText.includes("2 → 12"));
      assert.equal(await dLight.page.inputValue("#demoAdoptReason"),"仅采纳 CT 击杀，保留整图人工记录");
      assert.equal(await field.isChecked(), false);
      assert.equal(await dLight.page.isChecked("#demoDownloadDefaultCb"), false);
      await field.check();
      await dLight.page.check("#demoDownloadDefaultCb");
      await submitted(dLight.page, "#demoAdoptSubmitBtn", "/adopt");
      await dLight.page.waitForFunction(() => document.querySelector("#opsDemosList").innerText.includes("已指定前台下载"));
      assert.deepEqual((await readField(fixture.first_pid, "ct")).fields, {kills:12});
      assert.equal((await readField(fixture.first_pid, "all")).fields.kills, 19);
      assert.deepEqual((await readField(fixture.first_pid, "t")).fields, {});
      if (fixture.real_demo) {
        const original = fs.statSync(fixture.real_demo);
        await dLight.page.setInputFiles("#demoUploadFile", fixture.real_demo);
        const upload = await submitted(dLight.page, "#demoUploadSubmitBtn", "/api/demos");
        assert.equal(upload.original.byte_count, original.size);
        const id = upload.original.demo_id;
        const jobs = [];
        for (let attempt = 0; attempt < 2; attempt++) {
          const job = await submitted(dLight.page, `[data-action="parse-demo"][data-demo-id="${id}"]`, `/demos/${id}/parse`);
          assert.equal(job.status, "ready");
          jobs.push(job.analysis_id);
          await dLight.page.waitForFunction(jobId => document.querySelector("#opsDemoPreviewTitle").textContent.includes("Analysis #" + jobId + " "), job.analysis_id);
          assert(await dLight.page.locator("#demoAdoptSubmitBtn").isDisabled());
        }
        assert.notEqual(...jobs);
        const detail = await (await dLight.page.request.get(origin + `/admin/matches/${fixture.mid}/api/demos/${id}`)).json();
        assert.equal(detail.original.analyses.length, 2);
        const download = dLight.page.waitForEvent("download");
        await dLight.page.click(`a[href$="/api/demos/${id}/file"]`);
        assert.equal(fs.statSync(await (await download).path()).size, original.size);
        assert.equal(fs.statSync(fixture.real_demo).mtimeMs, original.mtimeMs);
        console.log("真实录像：上传、两次独立解析、阻止错配采纳、原件下载均通过。");
      }

      // Tab 3: Results, Explicit Settle & Predictions
      await dLight.page.click('[data-ops-tab="results"]');
      const beforeSettleText = await dLight.page.locator("#opsSeriesContainer").innerText();
      assert(beforeSettleText.includes("正式完赛（结算本场）"), "Expected explicit settle button before settlement");
      await dLight.page.click('[data-action="open-series-settle"]');
      await dLight.page.waitForSelector("#seriesActionDialog[open]");
      await dLight.page.fill("#seriesActionReason", "浏览器验收正式完赛");
      await dLight.page.click("#seriesActionSubmitBtn");
      await dLight.page.waitForFunction(() => {
        const txt = document.getElementById("opsPredictionsContainer")?.innerText || "";
        return txt.includes("8 分") && txt.includes("0 分");
      });
      report.push(await checkLayout(dLight.page, "ops-results-desktop-light", "ops-results-desktop-light.png", false));

      // Tab 4: Stats Revision Workbench (test 0 vs null, preview, save)
      await dLight.page.click('[data-ops-tab="stats"]');
      await dLight.page.waitForSelector('.ops-stat-input[data-stat-field="kills"]');
      // Switch to player 2 (has all unknown/null fields -> verify inputs are blank, NOT 0!)
      await dLight.page.selectOption("#statsPlayerSelect", String(fixture.second_pid));
      await dLight.page.waitForFunction(() => {
        const el = document.querySelector('.ops-stat-input[data-stat-field="kills"]');
        return el && el.value === "";
      });
      // Set kills to explicit 0, preview, and save
      await dLight.page.fill('.ops-stat-input[data-stat-field="kills"]', "0");
      await dLight.page.fill("#statsReasonInput", "核对记分板：明确零击杀");
      await dLight.page.click("#statsPreviewBtn");
      await dLight.page.waitForSelector("#statsPreviewArea:not([hidden])");
      const statsPrevText = await dLight.page.locator("#statsPreviewArea").innerText();
      assert(statsPrevText.includes("-"), "Expected before value '-'");
      const base = `/admin/matches/${fixture.mid}/operations`;
      const before = await readField(fixture.second_pid, "all");
      await postJson(dLight.page, base + "/stats", {map_run_id:fixture.r1, player_id:fixture.second_pid,
        scope:"t", fields:{assists:2}, expected_revision:before.revision, reason:"另一位管理员先核对 T 方助攻"});
      const stale = dLight.page.waitForResponse(r => r.url().endsWith(base + "/stats") && r.status() === 409);
      await dLight.page.click("#statsApplyBtn");
      await stale;
      await dLight.page.waitForSelector("#statsInlineError:not([hidden])");
      assert.equal(await dLight.page.inputValue("#statsReasonInput"), "核对记分板：明确零击杀");
      assert.equal(await dLight.page.inputValue('.ops-stat-input[data-stat-field="kills"]'), "0");
      assert(await dLight.page.locator("#statsApplyBtn").isDisabled());
      assert.equal((await readField(fixture.second_pid, "all")).fields.kills, undefined);
      await dLight.page.click("#statsPreviewBtn");
      await submitted(dLight.page, "#statsApplyBtn", "/stats");
      await dLight.page.waitForFunction(() => {
        return document.querySelector('.ops-stat-input[data-stat-field="kills"]')?.value === "0" && document.querySelector("#statsReasonInput")?.value === "";
      });
      // Verify kills is now 0 and untouched assists is still empty ('')
      const killsVal = await dLight.page.inputValue('.ops-stat-input[data-stat-field="kills"]');
      const assistsVal = await dLight.page.inputValue('.ops-stat-input[data-stat-field="assists"]');
      assert.equal(killsVal, "0", "Explicit 0 must remain 0");
      assert.equal(assistsVal, "", "Untouched unknown must remain blank");
      report.push(await checkLayout(dLight.page, "ops-stats-desktop-light", "ops-stats-desktop-light.png", false));

      // Managed Event Bracket page
      await dLight.page.goto(`${origin}/admin/events/${fixture.eid}/bracket`, { waitUntil: "load" });
      await dLight.page.evaluate(() => document.fonts.ready);
      const brText = await dLight.page.locator("body").innerText();
      assert(brText.includes("托管赛事晋级管理"), "Expected managed bracket page");
      assert(brText.includes("总决赛"), "Expected downstream match in bracket table");
      report.push(await checkLayout(dLight.page, "bracket-managed-desktop-light", "bracket-managed-desktop-light.png", false));

      assert.deepEqual(dLight.failed, [`/admin/matches/${fixture.mid}/api/demos/adopt:409`, base + "/stats:409"]);
      assert.deepEqual(dLight.errors.filter(e => !e.includes("409 (CONFLICT)")), []);
    } finally {
      await dLight.ctx.close();
    }

    // 2. Desktop Dark ZH
    const dDark = await newAdminPage(browser, { width: 1440, height: 900, lang: "zh", theme: "dark" });
    try {
      await dDark.page.goto(`${origin}/admin/matches/${fixture.mid}/operate`, { waitUntil: "load" });
      await dDark.page.evaluate(() => document.fonts.ready);
      report.push(await checkLayout(dDark.page, "ops-runs-desktop-dark", "ops-runs-desktop-dark.png", false));
      await dDark.page.click('[data-ops-tab="stats"]');
      await dDark.page.waitForSelector('.ops-stat-input[data-stat-field="kills"]');
      report.push(await checkLayout(dDark.page, "ops-stats-desktop-dark", "ops-stats-desktop-dark.png", false));
      assert.deepEqual(dDark.errors, [], "Desktop dark errors: " + dDark.errors.join("; "));
    } finally {
      await dDark.ctx.close();
    }

    // 3. Desktop Light EN — verify zero CJK leaks across all tabs + managed bracket!
    const dEn = await newAdminPage(browser, { width: 1440, height: 900, lang: "en", theme: "light" });
    try {
      await dEn.page.goto(`${origin}/admin/matches/${fixture.mid}/operate`, { waitUntil: "load" });
      await dEn.page.evaluate(() => document.fonts.ready);
      report.push(await checkLayout(dEn.page, "ops-runs-desktop-en", "ops-runs-desktop-en.png", true));

      await dEn.page.focus('[data-ops-tab="runs"]');
      await dEn.page.keyboard.press("ArrowRight");
      assert.equal(await dEn.page.locator('[role="tab"][aria-selected="true"]').getAttribute("data-ops-tab"), "demos");
      await dEn.page.click(`[data-action="toggle-analyses"][data-demo-id="${fixture.demo1_id}"]`);
      await dEn.page.click(`[data-action="preview-analysis"][data-analysis-id="${fixture.analysis_id}"]`);
      await dEn.page.waitForSelector("#opsDemoPreviewPanel:not([hidden])");
      report.push(await checkLayout(dEn.page, "ops-demos-desktop-en", "ops-demos-desktop-en.png", true));
      await dEn.page.click('[data-ops-tab="results"]');
      report.push(await checkLayout(dEn.page, "ops-results-desktop-en", "ops-results-desktop-en.png", true));

      await dEn.page.click('[data-ops-tab="stats"]');
      await dEn.page.waitForSelector('.ops-stat-input[data-stat-field="kills"]');
      report.push(await checkLayout(dEn.page, "ops-stats-desktop-en", "ops-stats-desktop-en.png", true));

      await dEn.page.goto(`${origin}/admin/events/${fixture.eid}/bracket`, { waitUntil: "load" });
      await dEn.page.evaluate(() => document.fonts.ready);
      report.push(await checkLayout(dEn.page, "bracket-managed-desktop-en", "bracket-managed-desktop-en.png", true));
      assert.deepEqual(dEn.errors, [], "Desktop EN errors: " + dEn.errors.join("; "));
    } finally {
      await dEn.ctx.close();
    }

    // 4. Mobile Light ZH (390x844) — verify zero horizontal overflow
    const mLight = await newAdminPage(browser, { width: 390, height: 844, lang: "zh", theme: "light" });
    try {
      await mLight.page.goto(`${origin}/admin/matches/${fixture.mid}/operate`, { waitUntil: "load" });
      await mLight.page.evaluate(() => document.fonts.ready);
      report.push(await checkLayout(mLight.page, "ops-runs-mobile-light", "ops-runs-mobile-light.png", false));

      await mLight.page.goto(`${origin}/admin/events/${fixture.eid}/bracket`, { waitUntil: "load" });
      await mLight.page.evaluate(() => document.fonts.ready);
      report.push(await checkLayout(mLight.page, "bracket-managed-mobile-light", "bracket-managed-mobile-light.png", false));
      const voter = await browser.newContext({viewport:{width:390,height:844}});
      await voter.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
      await voter.addCookies([{...fixture.viewer_cookie,url:origin}]);
      const vote = await voter.newPage();
      await vote.goto(origin + "/matches/" + fixture.target_mid);
      await vote.click('[data-vote="t1"]');
      await vote.waitForSelector(".vote-voted-hint");
      await voter.close();
      const page = mLight.page;
      const base = `/admin/matches/${fixture.mid}/operations`;
      const panel = async () => (await page.request.get(origin + base + "/panel-context")).json();
      const settled = await panel();
      const decider = settled.overview.results.maps[2];
      await page.goto(origin + `/admin/matches/${fixture.mid}/operate#results`);
      await page.click(`[data-action="open-confirm-map"][data-map-id="${decider.scheduled_map_id}"]`);
      await page.fill("#confirmMapScore1","7");
      await page.fill("#confirmMapScore2","13");
      await page.fill("#confirmMapReason","复核决胜图，逐席保留下游原对阵");
      let choices = page.locator("#confirmMapRetentionBox .ops-retain-cb");
      assert.equal(await choices.count(),2);
      await choices.nth(0).check();
      assert.equal(await page.locator("#confirmMapForm").evaluate(f => f.checkValidity()),false);
      await choices.nth(1).check();
      await postJson(page, base + "/confirm-map", {scheduled_map_id:decider.scheduled_map_id, map_run_id:decider.map_run_id,
        score1:13, score2:11, expected_revision:decider.revision, reason:"另一位管理员更新同胜方的图分"});
      const conflict = page.waitForResponse(r => r.url().endsWith("/confirm-map") && r.status() === 409);
      await page.click("#confirmMapForm [type=submit]");
      await conflict;
      await page.click("#confirmMapReload");
      await page.waitForFunction(() => document.querySelector("#confirmMapContext").textContent.includes("13 : 11"));
      assert.equal(await page.inputValue("#confirmMapReason"),"复核决胜图，逐席保留下游原对阵");
      assert.equal(await page.inputValue("#confirmMapScore1"),"7");
      assert.equal((await panel()).history.retained.length,0);
      await choices.nth(0).check();
      await choices.nth(1).check();
      report.push(await checkLayout(page, "手机逐席保留预览", "retention-mobile.png", false));
      await submitted(page,"#confirmMapForm [type=submit]","/confirm-map");
      const corrected = await panel();
      assert.equal(corrected.history.retained.length,2);
      assert(corrected.context.downstream_links.every(link => link.detached));
      assert.deepEqual(corrected.context.predictions.votes.map(v => v.points_earned),[0,3]);
      await page.click('[data-action="open-series-reopen"]');
      await page.fill("#seriesActionReason","复核后重新开启");
      await postJson(page, base + "/confirm-map", {scheduled_map_id:decider.scheduled_map_id, map_run_id:decider.map_run_id,
        score1:6, score2:13, expected_revision:corrected.overview.results.maps[2].revision, reason:"另一位管理员订正一回合"});
      const oldSeries = page.waitForResponse(r => r.url().endsWith("/reopen") && r.status() === 409);
      await page.click("#seriesActionSubmitBtn");
      await oldSeries;
      await page.click("#seriesActionReload");
      await page.waitForSelector("#seriesActionReload", {state:"hidden"});
      assert.equal(await page.inputValue("#seriesActionReason"),"复核后重新开启");
      await submitted(page,"#seriesActionSubmitBtn","/reopen");
      assert.equal((await panel()).context.predictions.settled_count,0);
      await page.click('[data-action="open-series-settle"]');
      await submitted(page,"#seriesActionSubmitBtn","/settle");
      await playFinal(page, report);
      assert.deepEqual(mLight.failed, [base + "/confirm-map:409", base + "/reopen:409",
        `/admin/matches/${fixture.target_mid}/operations/technical-replay:409`]);
      assert.deepEqual(mLight.errors.filter(e => !e.includes("409 (CONFLICT)")), []);
    } finally {
      await mLight.ctx.close();
    }
    const mEn = await newAdminPage(browser, {width:390, height:844, lang:"en", theme:"dark"});
    try {
      await mEn.page.goto(origin + `/admin/matches/${fixture.mid}/operate#stats`);
      await mEn.page.waitForSelector('.ops-stat-input[data-stat-field="kills"]');
      for (const [scope, expected] of [["ct","12"], ["t",""], ["all","19"]]) {
        await mEn.page.click(`[data-stats-scope="${scope}"]`);
        await mEn.page.waitForFunction(v => document.querySelector('.ops-stat-input[data-stat-field="kills"]')?.value === v, expected);
      }
      await mEn.page.locator(".ops-stat-group h3").first().evaluate(el => el.scrollIntoView({block:"center"}));
      assert(await mEn.page.locator("[data-stat-row]").first().evaluate(row => {
        const field = row.querySelector("input").getBoundingClientRect();
        const box = row.getBoundingClientRect();
        return field.left >= box.left && field.right <= box.right && field.bottom <= box.bottom;
      }));
      report.push(await checkLayout(mEn.page, "ops-stats-mobile-dark-en", "ops-stats-mobile-dark-en.png", true));
      assert.deepEqual(mEn.errors, []);
      assert.deepEqual(mEn.failed, []);
    } finally {
      await mEn.ctx.close();
    }
  } catch (err) {
    fatal = true;
    console.error("AUDIT FAILURE:", err);
  } finally {
    await browser.close();
  }

  console.log(JSON.stringify({ report, fatal }, null, 2));
  const hasOverflow = report.some(r => r.overflow);
  const hasLeaks = report.some(r => r.cjkLeaks && r.cjkLeaks.length > 0);
  if (fatal || hasOverflow || hasLeaks) {
    if (hasOverflow) console.error("OVERFLOW DETECTED:", report.filter(r => r.overflow));
    if (hasLeaks) console.error("EN CJK LEAKS DETECTED:", report.filter(r => r.cjkLeaks.length > 0));
    process.exit(1);
  }
})();
