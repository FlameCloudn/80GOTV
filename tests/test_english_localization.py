"""Regression checks for 80GOTV English localization and glossary consistency."""

import json
import subprocess
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables
from site_core.host import write

ROOT = Path(__file__).resolve().parents[1]


class EnglishLocalizationTests(unittest.TestCase):
    def test_js_syntax_and_forbidden_terms(self):
        js_files = [
            ROOT / "static/js/i18n.js",
            ROOT / "static/js/admin_event_roster.js",
            ROOT / "static/js/admin_form_guard.js",
            ROOT / "static/js/site_dialogs.js",
        ]
        for js_path in js_files:
            proc = subprocess.run(["node", "--check", str(js_path)], capture_output=True, text=True, check=False)
            self.assertEqual(proc.returncode, 0, msg=f"Syntax check failed for {js_path}: {proc.stderr}")

        i18n_src = (ROOT / "static/js/i18n.js").read_text(encoding="utf-8")
        for banned in ("WebP", "Most flashed", "centred", "unrecognised"):
            self.assertNotIn(banned, i18n_src)

    def test_site_translate_contracts_and_context_rules(self):
        script = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');

function loadRuntime(lang, nodes) {
  const domReady = [];
  const docNodes = nodes || [];
  const makeEl = () => {
    const attrs = {};
    return {
      style: {},
      innerHTML: '',
      value: '',
      id: '',
      className: '',
      classList: { add() {}, remove() {}, contains() { return false; } },
      setAttribute(k, v) { attrs[k] = String(v); },
      getAttribute(k) { return attrs[k] ?? null; },
      hasAttribute(k) { return Object.prototype.hasOwnProperty.call(attrs, k); },
      addEventListener() {},
    };
  };
  const sandbox = {
    console,
    Node: { TEXT_NODE: 3, ELEMENT_NODE: 1 },
    NodeFilter: { SHOW_TEXT: 4 },
    localStorage: { getItem: (k) => (k === 'siteLang' ? lang : null), setItem() {}, removeItem() {} },
    location: { reload() {} },
    document: {
      title: '80GOTV',
      documentElement: { classList: { remove() {}, add() {}, contains() { return false; } }, lang: 'zh-CN' },
      body: {
        nodeType: 1,
        appendChild() {},
        hasAttribute: () => false,
        querySelectorAll: () => [],
        matches: () => false,
        closest: () => null,
      },
      createTreeWalker: () => {
        let idx = -1;
        return {
          currentNode: null,
          nextNode() {
            idx += 1;
            if (idx < docNodes.length) {
              this.currentNode = docNodes[idx];
              return true;
            }
            return false;
          },
        };
      },
      querySelector: () => null,
      querySelectorAll: () => [],
      getElementById: () => null,
      addEventListener(ev, fn) { if (ev === 'DOMContentLoaded') domReady.push(fn); },
      createElement: () => makeEl(),
      readyState: 'loading',
    },
    window: { matchMedia: () => ({ matches: false }), addEventListener() {} },
    MutationObserver: function() { return { observe() {}, disconnect() {} }; },
    navigator: { language: 'zh-CN' },
  };
  sandbox.window.document = sandbox.document;
  sandbox.window.localStorage = sandbox.localStorage;
  sandbox.window.location = sandbox.location;
  vm.runInNewContext(src, sandbox);
  domReady.forEach((fn) => fn());
  return sandbox;
}

const en = loadRuntime('en');
const trEn = en.window.siteTranslate;
const expectedEn = [
  ['出场阵容', 'Lineups'],
  ['赛事运营', 'Tournament operations'],
  ['进行中与即将开始', 'Live and upcoming'],
  ['开始时间', 'Start date and time'],
  ['当前设定：未设置', 'Current time: not set'],
  ['3 个待审核', '3 pending reviews'],
  ['4 条待处理', '4 pending items'],
  ['待处理反馈 (4)', 'Feedback to review (4)'],
  ['比赛已结束，新增保存 3 条 Game Log', 'Match completed; 3 new Game Log entries saved'],
  ['数据保存失败：该地图比分尚未确认，不能按旧的 30 回合默认值保存', 'Stats save failed: The map score has not been confirmed; the old default of 30 rounds cannot be used'],
  ['比赛保存失败：比分尚未达到该赛制的获胜条件', 'Match save failed: The score has not reached the winning condition for this format'],
  ['工作台', 'Overview'],
  ['候补', 'Reserve'],
  ['替补', 'Substitute'],
  ['最多闪白', 'Most enemies flashed'],
  ['在线 BP', 'Online veto'],
  ['BP 房间', 'Map veto room'],
  ['BP 房间 - Team A 对 Team B', 'Map veto room - Team A vs Team B'],
  ['首五已确认 · 保留初始 4 / 5', 'Initial confirmed · Retains 4/5 initial'],
  ['操作失败（状态码 409）', 'Action failed (HTTP 409)'],
  ['冻结失败（状态码 409）', 'Lock failed (HTTP 409)'],
  ['请选择第 1 方的本届参赛队伍', 'Select an Event Entrant for Side 1'],
  ['Team A 选', 'Picked by Team A'],
  ['图 1', 'Map 1'],
  ['测试', 'Beta'],
  ['已完成', 'Completed'],
  ['待定', 'TBD'],
];

const mismatches = [];
for (const [zh, exp] of expectedEn) {
  const got = trEn(zh);
  if (got !== exp) mismatches.push({ zh, got, exp });
}

// Verify contextual .test-badge handling vs regular .badge ('Beta') via real DOM walk
const testNodeEn = {
  nodeType: 3,
  nodeValue: '测试',
  parentElement: {
    tagName: 'SPAN',
    classList: { contains: (c) => c === 'test-badge' },
    matches: () => false,
    closest: () => null,
  },
};
const betaNodeEn = {
  nodeType: 3,
  nodeValue: '测试',
  parentElement: {
    tagName: 'SMALL',
    classList: { contains: (c) => c === 'badge' },
    matches: () => false,
    closest: () => null,
  },
};
loadRuntime('en', [testNodeEn, betaNodeEn]);
if (testNodeEn.nodeValue !== 'Test') {
  mismatches.push({ ctx: '.test-badge en', got: testNodeEn.nodeValue, exp: 'Test' });
}
if (betaNodeEn.nodeValue !== 'Beta') {
  mismatches.push({ ctx: '.badge en', got: betaNodeEn.nodeValue, exp: 'Beta' });
}

const testNodeZh = {
  nodeType: 3,
  nodeValue: 'Test',
  parentElement: {
    tagName: 'SPAN',
    classList: { contains: (c) => c === 'test-badge' },
    matches: () => false,
    closest: () => null,
  },
};
const keepZhTerms = ['Rating', 'Impact', 'ADR', 'KAST', 'FK', 'IMP', 'Mirage', 'Dust2', 'Demo', 'GSI', 'GOTV', 'Beta', 'Test'];
const keepZhNodes = keepZhTerms.map((term) => ({
  nodeType: 3,
  nodeValue: term,
  parentElement: {
    tagName: 'SPAN',
    classList: { contains: () => false },
    matches: () => false,
    closest: () => null,
  },
}));
loadRuntime('zh', [testNodeZh, ...keepZhNodes]);
if (testNodeZh.nodeValue !== '测试') {
  mismatches.push({ ctx: '.test-badge zh', got: testNodeZh.nodeValue, exp: '测试' });
}

keepZhTerms.forEach((term, i) => {
  const got = keepZhNodes[i].nodeValue;
  if (got !== term) mismatches.push({ keepZh: term, got, exp: term });
});

console.log(JSON.stringify({ checked: expectedEn.length, mismatches }));
if (mismatches.length) process.exit(1);
"""
        proc = subprocess.run(
            ["node", "-e", script, str(ROOT / "static/js/i18n.js")],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=f"{proc.stdout}\n{proc.stderr}")

    def test_templates_compile_and_render_with_i18n_guards(self):
        templates = [t for t in app.jinja_env.list_templates() if t.endswith(".html")]
        for tpl in templates:
            app.jinja_env.get_template(tpl)

        with tempfile.TemporaryDirectory(prefix="i18n-tpl-") as td:
            db_path = Path(td) / "test.db"
            with patch.object(Config, "DATABASE", str(db_path)), patch.dict(
                app.config, {"TESTING": True, "SESSION_COOKIE_SECURE": False}
            ):
                init_tables()
                with closing(get_db()) as db:
                    with write(db):
                        admin_id = db.execute(
                            "INSERT INTO admins(username,password_hash) VALUES('i18n-admin','disabled')"
                        ).lastrowid
                        t1 = db.execute("INSERT INTO teams(name,short_name) VALUES('远岸队','YA')").lastrowid
                        t2 = db.execute("INSERT INTO teams(name,short_name) VALUES('星火队','XH')").lastrowid
                        start_day = (date.today() + timedelta(days=1)).isoformat()
                        end_day = (date.today() + timedelta(days=5)).isoformat()
                        eid = db.execute(
                            "INSERT INTO events(name,short_name,slug,start_date,end_date,status) VALUES('双语杯','I18N','i18n-cup',?,?,'upcoming')",
                            (start_day, end_day),
                        ).lastrowid
                        mid = db.execute(
                            "INSERT INTO matches(event_id,team1_id,team2_id,match_time,bo_format,status,is_test_mode,slug) VALUES(?,?,?,'2026-11-20 20:00','BO3','upcoming',1,'ya-vs-xh')",
                            (eid, t1, t2),
                        ).lastrowid

                client = app.test_client()
                with client.session_transaction() as sess:
                    sess.update(admin_id=admin_id, admin_username="i18n-admin", csrf_token="tok")

                for url in ("/", "/stats", "/events", f"/bp/{mid}", f"/matches/{mid}/report", "/admin/", "/admin/matches"):
                    res = client.get(url)
                    self.assertEqual(res.status_code, 200, msg=f"Unexpected status {res.status_code} on {url}")

                bp_html = client.get(f"/bp/{mid}").get_data(as_text=True)
                self.assertIn("bpTeamSpan", bp_html)
                self.assertIn("data-i18n-ignore", bp_html)

                report_html = client.get(f"/matches/{mid}/report").get_data(as_text=True)
                self.assertNotIn("on{{ item.alive_ct", report_html)

                admin_matches_html = client.get("/admin/matches").get_data(as_text=True)
                self.assertIn('<span class="test-badge">测试</span>', admin_matches_html)


if __name__ == "__main__":
    unittest.main()
