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
  ".player-directory-avatar-fallback", ".pp-portrait-fallback", ".award-player-avatar-fallback",
  "[data-i18n-ignore]", "[contenteditable=\"true\"]",
].join(",");

const CJK_RE = /[\u3400-\u9fff\uf900-\ufaff]/;

async function collectCjkLeaks(page) {
  return page.evaluate(({ ignoredSel }) => {
    const leaks = [];
    const cjk = /[\u3400-\u9fff\uf900-\ufaff]/;
    const isHidden = (el) => {
      if (!el || el.closest("dialog:not([open])")) return true;
      const st = getComputedStyle(el);
      return st.display === "none" || st.visibility === "hidden";
    };
    const isIgnoredEl = (el) => Boolean(el && (el.closest(ignoredSel)));
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      const val = (n.nodeValue || "").trim();
      if (!val || !cjk.test(val)) continue;
      const p = n.parentElement;
      if (!p || /^(SCRIPT|STYLE|TEXTAREA|NOSCRIPT)$/.test(p.tagName)) continue;
      if (isIgnoredEl(p) || isHidden(p)) continue;
      // #languageSelect intentionally keeps native '中文' label for language switching
      if (p.closest("#languageSelect") && val === "中文") continue;
      leaks.push({ tag: p.tagName.toLowerCase(), cls: p.className || "", text: val.slice(0, 120) });
    }
    for (const el of document.querySelectorAll("[placeholder], [title], [aria-label]")) {
      if (isIgnoredEl(el) || isHidden(el)) continue;
      for (const attr of ["placeholder", "title", "aria-label"]) {
        const av = (el.getAttribute(attr) || "").trim();
        if (av && cjk.test(av)) {
          // aria-label like 'Delete event 往届传统杯' or 'Select <team> to confirm Initial Roster' legitimately preserves proper nouns
          if (attr === "aria-label" && (/^(Delete (event|team|player|news)|View (event|team)|Select .+ to confirm Initial Roster)\s*/.test(av))) {
            continue;
          }
          leaks.push({ tag: el.tagName.toLowerCase(), attr, cls: el.className || "", text: av.slice(0, 120) });
        }
      }
    }
    return leaks.slice(0, 30);
  }, { ignoredSel: IGNORED_SELECTOR });
}

async function auditPage(page, name, url, device, opts = {}) {
  const failed = new Set();
  const errors = [];
  const onResponse = r => {
    const p = new URL(r.url()).pathname;
    if (r.status() >= 400 && p !== "/static/images/map-quiz/anubis.webp") failed.add(p + ":" + r.status());
  };
  const onReqFail = req => { if (new URL(req.url()).origin === origin) failed.add(new URL(req.url()).pathname); };
  const onPageErr = err => errors.push(err.message);
  const onConsole = msg => {
    if (msg.type() === "error" && !msg.text().includes("404 (NOT FOUND)")) errors.push(msg.text());
  };
  page.on("response", onResponse);
  page.on("requestfailed", onReqFail);
  page.on("pageerror", onPageErr);
  page.on("console", onConsole);

  const resp = await page.goto(origin + url, { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);
  if (opts.interact) await opts.interact(page);
  await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
  const bodyText = await page.locator("body").innerText();
  const missingTexts = (opts.expectedTexts || []).filter(t => !bodyText.includes(t));
  const forbiddenTexts = (opts.forbiddenTexts || []).filter(t => bodyText.includes(t));
  const cjkLeaks = await collectCjkLeaks(page);
  const sizes = await page.evaluate(() => ({
    width: document.documentElement.clientWidth,
    scroll: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
  }));
  const file = `${name}-${device}.png`;
  if (opts.screenshot !== false) {
    await page.screenshot({ path: path.join(fixture.output, file), fullPage: true, animations: "disabled" });
  }

  page.off("response", onResponse);
  page.off("requestfailed", onReqFail);
  page.off("pageerror", onPageErr);
  page.off("console", onConsole);
  return {
    name, device, status: resp ? resp.status() : null,
    missingTexts, forbiddenTexts, cjkLeaks, ...sizes,
    overflow: sizes.scroll > sizes.width,
    failed: [...failed], errors, file: opts.screenshot === false ? null : file,
  };
}

(async () => {
  const browser = await chromium.launch({
    channel: "msedge",
    args: ["--disable-background-networking", "--no-proxy-server"],
  });
  const results = [];
  try {
    const pages = [
      ["home", "/", { expectedTexts: ["Matches", "Results", "Events"] }],
      ["news", "/news", { expectedTexts: ["News", "Spring Major Recap"] }],
      ["matches", "/matches", { expectedTexts: ["Matches"] }],
      ["results", "/results", { expectedTexts: ["Results"] }],
      ["events", "/events", { expectedTexts: ["Events"] }],
      ["event-detail", `/events/${fixture.legacy_eid}`, { expectedTexts: ["Teams", "Matches"] }],
      ["match-detail", `/matches/${fixture.mid_done}`, {
        expectedTexts: ["Veto"],
        forbiddenTexts: ["Most flashed"],
      }],
      ["match-report", `/matches/${fixture.mid_done}/report`, { expectedTexts: ["MATCH REPORT", "RATING"] }],
      ["players", "/players", { expectedTexts: ["Players"] }],
      ["player-detail", `/players/${fixture.player_id}`, { expectedTexts: ["RATING 2.0"] }],
      ["stats", "/stats", { expectedTexts: ["Statistics", "Rating"] }],
      ["predictions", "/predictions", { expectedTexts: ["Predictions"] }],
      ["dashboard", "/dashboard", { expectedTexts: ["Dashboard"] }],
      ["forum", "/forum", { expectedTexts: ["Forum", "Scrim discussion"] }],
      ["games", "/games", { expectedTexts: ["Guess the player", "Map locations", "Player Bingo"] }],
      ["admin-overview", "/admin/", {
        expectedTexts: ["Overview", "Tournament operations", "Test"],
        forbiddenTexts: ["Beta"],
      }],
      ["admin-events", "/admin/events", { expectedTexts: ["Events", "Roster"] }],
      ["admin-events-add", "/admin/events/add", {
        expectedTexts: ["Managed registration"],
        interact: async p => { await p.locator('input[name="registration_mode"][value="managed"]').check(); },
      }],
      ["admin-events-edit-legacy", `/admin/events/edit/${fixture.legacy_eid}`, { expectedTexts: ["Basic information"] }],
      ["admin-roster-preform", `/admin/events/${fixture.eid_a}/roster`, {
        expectedTexts: ["B. Reservations Awaiting Review"],
        interact: async p => {
          await p.locator('[data-open-review="claim"]').first().click();
          await p.locator("#dialogReviewReservation").waitFor({ state: "visible" });
          await p.locator("#reviewReasonInput").waitFor({ state: "visible" });
        },
      }],
      ["admin-roster-formed", `/admin/events/${fixture.eid_b}/roster`, {
        expectedTexts: ["Initial confirmed", "Retains 4/5 initial", "Team substitutes", "Reserve"],
      }],
      ["admin-matches", "/admin/matches", { expectedTexts: ["Manage matches", "Test"] }],
      ["admin-matches-add", "/admin/matches/add", {
        expectedTexts: ["Event Entrant"],
        interact: async p => {
          await p.selectOption("#eventIdSelect", String(fixture.eid_b));
          await p.locator("#side1_entrant_select").waitFor({ state: "visible" });
        },
      }],
      ["admin-matches-edit-roster", `/admin/matches/edit/${fixture.mid_b}`, {
        expectedTexts: ["Match Roster", "Initial Roster", "Current Roster"],
        interact: async p => { await p.locator('.match-tab[data-tab="roster"]').click(); },
      }],
      ["admin-registrations", "/admin/registrations", { expectedTexts: ["Registration reviews"] }],
      ["admin-feedback", "/admin/feedback", { expectedTexts: ["User feedback", "All feedback"] }],
    ];

    for (const [device, width, height] of [["desktop", 1440, 900], ["mobile", 390, 844]]) {
      const ctx = await browser.newContext({
        viewport: { width, height },
        isMobile: device === "mobile",
        hasTouch: device === "mobile",
        locale: "en-US",
        reducedMotion: "reduce",
        serviceWorkers: "block",
      });
      await ctx.addInitScript(() => {
        localStorage.setItem("siteLang", "en");
        localStorage.setItem("theme", "light");
      });
      await ctx.addCookies([{ ...fixture.cookie, url: origin, httpOnly: true, sameSite: "Lax" }]);
      await ctx.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
      const page = await ctx.newPage();

      for (const [name, url, opts] of pages) {
        const effOpts = (device === "mobile" && name === "admin-overview")
          ? { ...opts, expectedTexts: ["Overview", "Test"] }
          : opts;
        results.push(await auditPage(page, name, url, device, {
          ...effOpts,
          screenshot: device === "desktop" || [
            "home", "match-detail", "stats", "admin-overview",
            "admin-roster-formed", "admin-matches-edit-roster",
          ].includes(name),
        }));
      }

      // Live Veto Room interaction on desktop
      if (device === "desktop") {
        results.push(await auditPage(page, "bp-room", `/bp/${fixture.mid_bp}`, "desktop", {
          expectedTexts: ["Banned", "Reset veto", "click a map above"],
          interact: async p => {
            const title = await p.title();
            assert.ok(title.includes("Map veto room"), `Expected Veto title, got: ${title}`);
            const startBtn = p.getByRole("button", { name: /Start/ });
            if (await startBtn.count()) {
              await startBtn.click();
              await p.locator("button", { hasText: /Roll$/ }).first().waitFor({ state: "visible" });
              await p.locator("button", { hasText: /Roll$/ }).first().click();
              await p.waitForTimeout(150);
              const secondRoll = p.locator("button", { hasText: /Roll$/ }).first();
              if (await secondRoll.count()) {
                await secondRoll.click();
              }
              await p.getByRole("button", { name: /^First$/ }).waitFor({ state: "visible" });
              await p.getByRole("button", { name: /^First$/ }).click();
              await p.locator(".bp-map-card.clickable").first().waitFor({ state: "visible" });
              await p.locator(".bp-map-card.clickable").first().click();
              await p.locator(".bp-map-card.banned").first().waitFor({ state: "visible" });
            }
          },
        }));

        // Language switch roundtrip en -> zh -> en on /stats in a fresh context without forced initScript
        const swCtx = await browser.newContext({
          viewport: { width: 1440, height: 900 },
          locale: "en-US",
          reducedMotion: "reduce",
          serviceWorkers: "block",
        });
        await swCtx.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
        const swPage = await swCtx.newPage();
        await swPage.goto(origin + "/stats", { waitUntil: "load" });
        await swPage.evaluate(() => localStorage.setItem("siteLang", "en"));
        await swPage.reload({ waitUntil: "load" });
        const initialEn = await swPage.locator("body").innerText();
        assert.ok(initialEn.includes("Statistics") && initialEn.includes("Rating"), "Expected English /stats before toggle");
        await Promise.all([
          swPage.waitForNavigation({ waitUntil: "load" }),
          swPage.selectOption("#languageSelect", "zh"),
        ]);
        const zhBody = await swPage.locator("body").innerText();
        assert.ok(zhBody.includes("Rating") && zhBody.includes("统计"), "ZH switch should keep Rating and show Chinese headings");
        await Promise.all([
          swPage.waitForNavigation({ waitUntil: "load" }),
          swPage.selectOption("#languageSelect", "en"),
        ]);
        const enBody = await swPage.locator("body").innerText();
        assert.ok(enBody.includes("Statistics") && enBody.includes("Rating"), "EN switch-back should restore English Statistics");
        await swCtx.close();
      }

      await ctx.close();
    }
  } finally {
    fs.writeFileSync(path.join(fixture.output, "audit.json"), JSON.stringify(results, null, 2));
    await browser.close();
  }

  process.stdout.write(JSON.stringify(results, null, 2) + "\n");
  if (results.some(r => r.status !== 200 || r.missingTexts.length || r.forbiddenTexts.length || r.cjkLeaks.length || r.overflow || r.failed.length || r.errors.length)) {
    process.exitCode = 1;
  }
})().catch(err => {
  process.stderr.write(`${err.stack || err}\n`);
  process.exitCode = 1;
});
