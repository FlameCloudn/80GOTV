"use strict";

// Run the director's own TypeScript against captured Flask responses and an in-memory local DB.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { DatabaseSync } = require("node:sqlite");

const ts = require("typescript");
const sourcePath = path.resolve(__dirname, "../../fixtures/director/80gotv.ts");
const source = ts.createSourceFile(sourcePath, fs.readFileSync(sourcePath, "utf8"), ts.ScriptTarget.Latest, true);
const remaining = new Set([
  "status", "normalizeWebsiteUrl", "WebsiteHttpError", "fetchJson", "teamId", "playerId", "matchId",
  "broadcastPlayerName", "normalizedTeamName", "fillMissingTeamLogo", "fillMatchLogosFromEvent", "mapName",
  "buildVetos", "mergeWebsiteVetos", "upsertTeam", "upsertPlayer", "syncHudWebsiteConfig", "listWebsiteSources",
  "syncWebsiteEvent", "syncWebsiteMatch", "syncWebsiteSource", "resetForwardTarget", "syncWebsiteBp",
  "readSelectedMatchId", "checkWebsiteConnection", "requireMatchingReceipt", "isClosedMatchError",
  "sessionForMatch", "readSettingValue", "writeSettingValue", "queueWebsiteLiveData", "flushForward",
  "pendingPayload", "forwardTimer", "forwardAttempts", "forwardInFlight", "resultQueue", "websitePlayerPresentation",
]);
const fragments = [];
for (const statement of source.statements) {
  const name = ts.isVariableStatement(statement)
    ? statement.declarationList.declarations[0].name.getText(source)
    : statement.name?.getText(source);
  if (remaining.delete(name)) fragments.push(statement.getText(source));
}
assert.equal(remaining.size, 0, `缺少旧导播函数或状态：${[...remaining].join(", ")}`);
fragments.push("export { status, checkWebsiteConnection };");
const { outputText } = ts.transpileModule(fragments.join("\n"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});

async function verify() {
  const fixture = JSON.parse(fs.readFileSync(0, "utf8"));
  const base = "https://host-fixture.invalid";
  const requests = [];
  const timers = new Set();
  const db = new DatabaseSync(":memory:");
  try {
    db.exec(`CREATE TABLE teams (_id TEXT PRIMARY KEY, name, country, shortName, logo, extra);
      CREATE TABLE players (_id TEXT PRIMARY KEY, firstName, lastName, username, avatar, country, steamid, team, isCoach, extra);
      CREATE TABLE settings (key TEXT PRIMARY KEY, value);
      CREATE TABLE matches (id TEXT PRIMARY KEY, current, left_id, left_wins, right_id, right_wins, matchType, vetos);
      CREATE TABLE hud_configs (hud_id TEXT PRIMARY KEY, config_data TEXT);`);
    const localSetting = key => db.prepare("SELECT value FROM settings WHERE key=?").get(key)?.value || "";
    let forwardLiveData = false;
    const sandbox = {
      exports: {}, AbortSignal, URL, dbReady: Promise.resolve(),
      getSettings: async () => ({ websiteUrl: base, websiteMatchId: localSetting("websiteMatchId"),
        websiteGsiToken: fixture.fixtureToken, forwardLiveData }),
      dbRun: async (sql, args = []) => db.prepare(sql).run(...args),
      dbGet: async (sql, args = []) => db.prepare(sql).get(...args),
      dbAll: async (sql, args = []) => db.prepare(sql).all(...args),
      setTimeout: callback => (timers.add(callback), callback),
      clearTimeout: callback => timers.delete(callback),
      refreshGsiMatchContext: async () => {},
      steamUnavailableUntil: Number.MAX_SAFE_INTEGER,
      downloadAsset: () => assert.fail("样例不应访问网站文件"),
      fetchSteamPublicProfile: () => assert.fail("样例不应访问 Steam"),
      console: { log: () => {}, warn: (...args) => assert.fail(args.join(" ")) },
      fetch: async (url, options) => {
        const parsed = new URL(url);
        const request = `${options.method || "GET"} ${parsed.pathname}`;
        requests.push(request);
        assert.equal(parsed.origin, base);
        assert.equal(options.headers.Accept, "application/json");
        assert.ok(options.signal instanceof AbortSignal);
        assert.ok(Object.hasOwn(fixture.responses, request), `没有捕获 Flask 应答：${request}`);
        if (parsed.pathname.endsWith("/live")) {
          assert.equal(options.headers["X-80GOTV-Token"], fixture.fixtureToken);
          const body = JSON.parse(options.body);
          assert.equal(body.map.name, "de_anubis");
          assert.equal(body._80gotv.session_id, sandbox.exports.status.sessionId);
          assert.equal(body.auth, undefined);
        }
        const response = fixture.responses[request];
        return { ok: response.status < 300, status: response.status, json: async () => structuredClone(response.json) };
      },
    };
    vm.runInNewContext(outputText, sandbox, { filename: sourcePath });
    const { status, listWebsiteSources, syncWebsiteSource, checkWebsiteConnection, syncWebsiteBp, queueWebsiteLiveData } = sandbox.exports;
    const sources = await listWebsiteSources();
    assert.deepEqual(new Set(sources.map(s => s.key)), new Set([
      String(fixture.match), String(fixture.swapped), `event:${fixture.event}`, `event:${fixture.legacy}`,
    ]));
    assert.ok(sources.some(s => s.key === `event:${fixture.legacy}` && s.label.includes("旧版赛事样例")));

    await syncWebsiteSource(`event:${fixture.legacy}`);
    const oldTeam = `80gotv-team-registration-${fixture.legacyRegistration}`;
    assert.equal(db.prepare("SELECT name FROM teams WHERE _id=?").get(oldTeam).name, "旧版报名队");
    const roster = await syncWebsiteSource(`event:${fixture.event}`);
    assert.equal(roster.source_type, "event");
    assert.equal(status.forwardTargetMatchId, null);
    assert.equal(localSetting("websiteMatchId"), `event:${fixture.event}`);
    const teamIds = fixture.teams.map(t => `80gotv-team-registration-${t.registration}`);
    const checkRoster = () => {
      for (const [index, id] of teamIds.entries()) {
        const players = db.prepare("SELECT steamid,extra FROM players WHERE team=? ORDER BY json_extract(extra,'$.matchSlot')").all(id);
        assert.deepEqual(players.map(p => p.steamid), fixture.teams[index].steam);
        assert.deepEqual(players.map(p => JSON.parse(p.extra).matchSlot), [1, 2, 3, 4, 5]);
      }
      assert.equal(db.prepare("SELECT COUNT(*) AS n FROM players WHERE team IS NULL AND json_extract(extra,'$.isSubstitute')").get().n, 2);
    };
    checkRoster();

    const selection = await syncWebsiteSource(String(fixture.match));
    assert.equal(selection.source_type, "match");
    assert.equal(selection.match.roster_locked, true);
    assert.equal(selection.match.ready_for_start, false);
    const selected = db.prepare("SELECT * FROM matches WHERE id=?").get(`80gotv-match-${fixture.match}`);
    assert.deepEqual([selected.left_id, selected.right_id], teamIds);
    assert.equal(selected.matchType, "bo1");
    const vetoes = JSON.parse(selected.vetos);
    assert.equal(vetoes.filter(v => v.type === "ban").length, 6);
    const plans = vetoes.filter(v => v.type !== "ban");
    assert.equal(plans.length, 1);
    const [plan] = plans;
    assert.deepEqual([plan.mapSlot, plan.mapName, plan.type, plan.mapEnd], [1, "de_anubis", "decider", false]);
    assert.equal(plan.openingCtTeamId, undefined); // Old director waits for actual decider-side evidence.
    await assert.rejects(checkWebsiteConnection(base, fixture.fixtureToken, fixture.match), /暂不能开赛/);
    assert.equal(await syncWebsiteBp(), false);
    assert.match(status.lastBpSyncError, /导播暂不进入正式状态/);
    assert.equal(db.prepare("SELECT vetos FROM matches WHERE id=?").get(selected.id).vetos, selected.vetos);

    async function flushOneFrame() {
      queueWebsiteLiveData({ map: { name: "de_anubis" }, auth: { token: "synthetic" } });
      assert.equal(timers.size, 1);
      const [flush] = timers;
      timers.delete(flush);
      await flush();
    }
    await flushOneFrame();
    const live = `POST /api/broadcast/matches/${fixture.match}/live`;
    assert.ok(!requests.includes(live));
    // A previously enabled sender still attempts POST; the actual host refusal cannot become an acknowledgement.
    forwardLiveData = true;
    await flushOneFrame();
    assert.equal(requests.filter(request => request === live).length, 1);
    assert.equal(status.confirmedMatchId, null);
    assert.equal(status.lastForwardAt, null);
    assert.match(status.lastError, /赛前准备/);

    await syncWebsiteSource(String(fixture.swapped));
    const swapped = db.prepare("SELECT left_id,right_id,current FROM matches WHERE id=?").get(`80gotv-match-${fixture.swapped}`);
    assert.deepEqual([swapped.left_id, swapped.right_id, swapped.current], [teamIds[1], teamIds[0], 1]);
    assert.deepEqual(new Set(db.prepare("SELECT _id FROM teams").all().map(t => t._id)), new Set([oldTeam, ...teamIds]));
    checkRoster();
    process.stdout.write("旧导播原函数：新旧列表、跨左右同队、本场排图、就绪和转发边界已核对。\n");
  } finally {
    db.close();
  }
}

verify().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
