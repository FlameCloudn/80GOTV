import os
import tempfile
import unittest
from io import BytesIO

from app import app
from config import Config
from models import get_db, init_tables


class AdminUxLogicOverhaulTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        Config.DATABASE = self.database_path
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()

        conn = get_db()
        conn.execute(
            "INSERT INTO events(name,short_name,slug,status,registration_open,start_date,end_date) VALUES('Cup A','CA','cup-a','upcoming',1,'2026-08-01','2026-08-10')"
        )
        self.event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO teams(name,short_name) VALUES('Team 1','T1')")
        self.team1_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO teams(name,short_name) VALUES('Team 2','T2')")
        self.team2_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO teams(name,short_name) VALUES('Team 3','T3')")
        self.team3_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        conn.execute(
            """INSERT INTO matches(
                   event_id,team1_id,team2_id,team1_score,team2_score,
                   match_time,bo_format,stage,status,
                   bp_password,server_address,server_password
               ) VALUES(?,?,?,?,?,'2026-08-01T20:00','BO1','小组赛','upcoming',
                        'orig-bp-hash','1.2.3.4:27015','orig-secret')""",
            (self.event_id, self.team1_id, self.team2_id, 0, 0),
        )
        self.match_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        self.client = app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["admin_id"] = 1
            browser_session["admin_username"] = "admin"
            browser_session["csrf_token"] = "test-token"

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config.update(
            TESTING=self.original_testing,
            SESSION_COOKIE_SECURE=self.original_secure_cookie,
        )
        try:
            os.remove(self.database_path)
        except OSError:
            pass

    def test_match_form_renders_tabbed_ui_and_removes_position_labels(self):
        """测试比赛修改表单渲染全新Tab结构，去除了MOBA几号位与红蓝方，引入快捷时间选择"""
        response = self.client.get(f"/admin/matches/edit/{self.match_id}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertIn("match-tabs", html)
        self.assertIn("基础与对阵", html)
        self.assertIn("地图与赛制", html)
        self.assertIn("出场名单与替补", html)
        self.assertIn("选手 1", html)
        self.assertNotIn("1号位", html)
        self.assertNotIn("红方", html)
        self.assertNotIn("蓝方", html)
        self.assertIn("time-picker-card", html)
        self.assertIn("sticky-form-actions", html)

    def test_upcoming_match_can_change_teams(self):
        """测试在赛前（upcoming）状态下，管理员可以直接修改对阵双方队伍"""
        response = self.client.post(
            f"/admin/matches/edit/{self.match_id}",
            data={
                "csrf_token": "test-token",
                "event_id": str(self.event_id),
                "match_time": "2026-08-01T20:00",
                "bo_format": "BO1",
                "stage": "小组赛",
                "status": "upcoming",
                "side1_type": "team",
                "side1_id": str(self.team1_id),
                "side2_type": "team",
                "side2_id": str(self.team3_id),  # 将队伍2更改为队伍3
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        conn = get_db()
        row = conn.execute(
            "SELECT team1_id, team2_id FROM matches WHERE id=?", (self.match_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(row["team1_id"], self.team1_id)
        self.assertEqual(row["team2_id"], self.team3_id)

    def test_completed_match_preserves_passwords_when_fields_omitted(self):
        """测试已结束比赛在隐藏服务器密码字段后提交时，数据库中原有凭据不丢失"""
        conn = get_db()
        conn.execute(
            "UPDATE matches SET status='completed', bp_password='keep-bp', server_password='keep-srv' WHERE id=?",
            (self.match_id,),
        )
        conn.commit()
        conn.close()

        response = self.client.post(
            f"/admin/matches/edit/{self.match_id}",
            data={
                "csrf_token": "test-token",
                "event_id": str(self.event_id),
                "match_time": "2026-08-01T20:00",
                "bo_format": "BO1",
                "stage": "决赛",
                "status": "completed",
                "map1": "mirage",
                "map1_t1": "13",
                "map1_t2": "7",
                # 注意：未提交 server_password 和 bp_password
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        conn = get_db()
        row = conn.execute(
            "SELECT bp_password, server_password FROM matches WHERE id=?",
            (self.match_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(row["bp_password"], "keep-bp")
        self.assertEqual(row["server_password"], "keep-srv")

    def test_chinese_event_short_name_is_preserved(self):
        """测试赛事中文简称（如'八十中杯'）不会被误过滤为空字符串"""
        response = self.client.post(
            "/admin/events/add",
            data={
                "csrf_token": "test-token",
                "name": "北京八十中秋季邀请赛",
                "short_name": "八十中杯",
                "start_date": "2026-10-01",
                "end_date": "2026-10-03",
                "status": "upcoming",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        conn = get_db()
        row = conn.execute(
            "SELECT short_name FROM events WHERE name='北京八十中秋季邀请赛'"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["short_name"], "八十中杯")

    def test_completed_event_forces_registration_closed(self):
        """测试已结束赛事会自动关闭报名，避免脏数据展示"""
        response = self.client.post(
            f"/admin/events/edit/{self.event_id}",
            data={
                "csrf_token": "test-token",
                "name": "Cup A",
                "short_name": "CA",
                "start_date": "2026-07-01",
                "end_date": "2026-07-03",
                "status": "completed",
                "registration_open": "1",  # 即使表单提交开启，也应强制为关闭
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        conn = get_db()
        row = conn.execute(
            "SELECT registration_open FROM events WHERE id=?", (self.event_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(row["registration_open"], 0)

    def test_existing_non_student_player_edit_without_group_username(self):
        """测试编辑老玩家/非八十中学生选手时，不会因为缺少群内昵称而被误拦截"""
        conn = get_db()
        conn.execute(
            "INSERT INTO players(nickname, is_bashizhong_student, group_username_override) VALUES('OldGuest', 0, NULL)"
        )
        player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        response = self.client.post(
            f"/admin/players/edit/{player_id}",
            data={
                "csrf_token": "test-token",
                "nickname": "OldGuestRenamed",
                "is_bashizhong_student": "0",
                "group_username": "",
                "team_id": str(self.team1_id),
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        conn = get_db()
        row = conn.execute(
            "SELECT nickname, team_id FROM players WHERE id=?", (player_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(row["nickname"], "OldGuestRenamed")
        self.assertEqual(row["team_id"], self.team1_id)

    def test_team_logo_upload_in_admin(self):
        """测试后台创建队伍时可直接上传队标文件"""
        from PIL import Image

        img = Image.new("RGB", (32, 32), color=(88, 129, 188))
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        response = self.client.post(
            "/admin/teams/add",
            data={
                "csrf_token": "test-token",
                "name": "LogoTeam",
                "short_name": "LT",
                "description": "测试上传队标",
                "logo": (buf, "team_logo.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        conn = get_db()
        row = conn.execute("SELECT logo FROM teams WHERE name='LogoTeam'").fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertTrue(row["logo"] and "team_logos/" in row["logo"])
        # 清理上传的临时队标
        from config import BASE_DIR

        logo_path = os.path.join(BASE_DIR, "static", "uploads", row["logo"])
        if os.path.exists(logo_path):
            try:
                os.remove(logo_path)
            except OSError:
                pass

    def test_admin_matches_filters_and_connect_copy(self):
        """测试比赛后台列表的筛选、搜索及一键进服指令功能"""
        conn = get_db()
        conn.execute("UPDATE matches SET match_time='2099-01-01T20:00' WHERE id=?", (self.match_id,))
        conn.commit()
        conn.close()

        # 1. 基础访问：检查包含筛选工具栏与复制按钮
        response = self.client.get("/admin/matches")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("matches-filter-toolbar", html)
        self.assertIn("全部 (1)", html)
        self.assertIn("未开始 (1)", html)
        self.assertIn("copy-connect-btn", html)
        self.assertIn('data-connect="connect 1.2.3.4:27015; password orig-secret"', html)

        # 2. 状态筛选：筛选未开始
        resp_upcoming = self.client.get("/admin/matches?status=upcoming")
        self.assertEqual(resp_upcoming.status_code, 200)
        self.assertIn("Team 1 对 Team 2", resp_upcoming.get_data(as_text=True))

        # 3. 状态筛选：筛选已结束（目前无结束比赛，应显示空提示）
        resp_completed = self.client.get("/admin/matches?status=completed")
        self.assertEqual(resp_completed.status_code, 200)
        self.assertIn("没有找到符合条件的比赛", resp_completed.get_data(as_text=True))

        # 4. 搜索队伍：匹配
        resp_search = self.client.get("/admin/matches?q=Team 1")
        self.assertEqual(resp_search.status_code, 200)
        self.assertIn("Team 1 对 Team 2", resp_search.get_data(as_text=True))

        # 5. 搜索不存在内容：空提示
        resp_none = self.client.get("/admin/matches?q=NoSuchTeamExists")
        self.assertEqual(resp_none.status_code, 200)
        self.assertIn("没有找到符合条件的比赛", resp_none.get_data(as_text=True))

