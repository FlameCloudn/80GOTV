"use strict";

// Replay Flask's actual responses through the original desktop functions, without starting Electron.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { DatabaseSync } = require("node:sqlite");

const desktopRoot = path.resolve(__dirname, "../../../jts-hud-manager");
const ts = require(path.join(desktopRoot, "node_modules/typescript"));
const sourcePath = path.join(desktopRoot, "src/main/server/integrations/80gotv.ts");
const source = ts.createSourceFile(sourcePath, fs.readFileSync(sourcePath, "utf8"), ts.ScriptTarget.Latest, true);
const names = new Set([
  "normalizeWebsiteUrl", "WebsiteHttpError", "fetchJson", "teamId", "playerId", "broadcastPlayerName",
  "upsertTeam", "upsertPlayer", "listWebsiteSources", "syncWebsiteEvent", "syncWebsiteSource", "resetForwardTarget"
]);
const pieces = [];
for (const statement of source.statements) {
  const name = ts.isVariableStatement(statement)
    ? statement.declarationList.declarations[0].name.getText(source)
    : statement.name?.getText(source);
  if (names.delete(name)) pieces.push(statement.getText(source));
}
assert.equal(names.size, 0, `找不到原导播函数：${[...names].join(", ")}`);
const { outputText } = ts.transpileModule(pieces.join("\n"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
});

async function replay() {
  const { responses, event_id: eventId, old_id: oldId, open_id: openId, group } = JSON.parse(fs.readFileSync(0, "utf8"));
  const base = "https://slice-preview.invalid";
  const requests = [];
  const status = { importedMatchId: 99, forwardTargetMatchId: 99, forwardGeneration: 1, sessionId: "fixture-session" };
  const resultQueue = [{ matchId: 99, generation: 1 }];
  const db = new DatabaseSync(":memory:");
  try {
    db.exec(`CREATE TABLE teams (_id TEXT PRIMARY KEY, name, country, shortName, logo, extra);
      CREATE TABLE players (_id TEXT PRIMARY KEY, firstName, lastName, username, avatar, country, steamid, team, isCoach, extra);
      CREATE TABLE settings (key TEXT PRIMARY KEY, value);`);
    const sandbox = {
      exports: {}, AbortSignal, URL, status, resultQueue,
      pendingPayload: {}, forwardAttempts: 1, forwardTimer: null,
      websitePlayerPresentation: new Map(), steamUnavailableUntil: Number.MAX_SAFE_INTEGER,
      getSettings: async () => ({ websiteUrl: base }),
      dbRun: async (sql, args) => db.prepare(sql).run(...args),
      dbGet: async (sql, args) => db.prepare(sql).get(...args),
      downloadAsset: () => assert.fail("合成样例不应下载图片"),
      fetchSteamPublicProfile: () => assert.fail("合成样例不应访问 Steam"),
      syncWebsiteMatch: () => assert.fail("赛事名单不应按比赛导入"),
      console: { warn: (...args) => assert.fail(args.join(" ")) },
      fetch: async (url, options) => {
        const parsed = new URL(url);
        const route = parsed.pathname;
        requests.push(route);
        assert.equal(parsed.origin, base);
        assert.equal(options.method || "GET", "GET");
        assert.equal(options.headers.Accept, "application/json");
        assert.ok(options.signal instanceof AbortSignal);
        assert.ok(Object.hasOwn(responses, route), `Flask 未提供应答：${route}`);
        const response = responses[route];
        return { ok: response.status === 200, status: response.status, json: async () => structuredClone(response.json) };
      }
    };
    vm.runInNewContext(outputText, sandbox, { filename: sourcePath });
    const { listWebsiteSources, syncWebsiteSource } = sandbox.exports;
    const sources = structuredClone(await listWebsiteSources());
    assert.deepEqual(new Set(sources.map(item => item.key)), new Set([`event:${eventId}`, `event:${oldId}`, `event:${openId}`]));
    assert.equal(sources.find(item => item.id === eventId).label, "新示例届 · 2 支队伍 · 1 名替补");
    assert.equal(sources.find(item => item.id === openId).label, "尚无队伍的示例届 · 0 支队伍 · 1 名替补");
    assert.ok(sources.every(item => item.source_type === "event" && typeof item.id === "number"));
    await syncWebsiteSource(`event:${oldId}`);
    const imported = await syncWebsiteSource(`event:${eventId}`);
    assert.equal(imported.source_type, "event");
    assert.equal(imported.summary, "新示例届：2 支队伍，1 名替补");
    assert.deepEqual(requests, ["/api/broadcast/matches", "/api/broadcast/events", `/api/broadcast/events/${oldId}`,
      `/api/broadcast/events/${eventId}`]);

    const localTeam = `80gotv-team-registration-${group}`;
    assert.equal(db.prepare("SELECT name FROM teams WHERE _id=?").get(localTeam).name, "新示例临时队");
    assert.equal(db.prepare("SELECT name FROM teams WHERE _id='80gotv-team-registration-31'").get().name, "旧示例队");
    assert.equal(db.prepare("SELECT count(*) AS n FROM teams").get().n, 3);
    const roster = db.prepare("SELECT steamid, extra FROM players WHERE team=? ORDER BY json_extract(extra,'$.matchSlot')").all(localTeam);
    const steam = id => String(76561198080000000n + BigInt(id));
    assert.deepEqual(roster.map(row => row.steamid), [1, 2, 3, 4, 11].map(steam));
    assert.deepEqual(roster.map(row => JSON.parse(row.extra).matchSlot), [1, 2, 3, 4, 5]);
    assert.equal(db.prepare("SELECT steamid FROM players WHERE _id='80gotv-player-21'").get().steamid, steam(21));
    const reserve = db.prepare("SELECT steamid, team, extra FROM players WHERE _id='80gotv-player-13'").get();
    assert.equal(reserve.steamid, steam(13));
    assert.equal(reserve.team, null);
    assert.equal(JSON.parse(reserve.extra).isSubstitute, true);
    assert.equal(db.prepare("SELECT 1 FROM players WHERE steamid=?").get(steam(12)), undefined);
    assert.equal(db.prepare("SELECT value FROM settings WHERE key='websiteMatchId'").get().value, `event:${eventId}`);
    assert.equal(status.importedMatchId, null);
    assert.equal(status.forwardTargetMatchId, null);
    assert.deepEqual(resultQueue, [{ matchId: 99, generation: 1 }]);
    process.stdout.write("原导播源码：赛事选择、旧届和新届同步、名单与待转发目标检查通过。\n");
  } finally {
    db.close();
  }
}

replay().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
