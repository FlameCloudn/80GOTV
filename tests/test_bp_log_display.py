"""比赛页 BP 记录拆分：系统生成的格式、管理员手写的格式、认不出的文字。"""

import unittest

from services.match_service import parse_bp_log

TEAM1 = ["T1", "U8", "U8"]
TEAM2 = ["T2", "G8 Esports", "G8"]

GENERATED_BO3 = """Roll: T1=39, T2=43 → T2 胜出
T2 选择先手
1. T2 Ban Anubis
2. T1 Ban Inferno
3. T2 Pick Nuke
4. T1 Pick Ancient
5. T2 Ban Cache
6. T1 Ban Dust2
7. Mirage 剩余
选边: Nuke → T 方
选边: Ancient → CT 方"""

GENERATED_BO1 = """Roll: T1=81, T2=69 → T1 胜出
T1 选择先手
1. T1 Ban Anubis
2. T1 Ban Cache
3. T2 Ban Inferno
4. T2 Ban Ancient
5. T2 Ban Mirage
6. T1 Ban Nuke
7. Dust2 剩余
选边: Dust2 → CT 方"""

HANDWRITTEN = """t3-myh66等 t4-Matsubara Kanon等
T3 BAN OP
T4 PICK MIRAGE
LEFT NUKE"""


def _parse(text):
    """拆分并确认拆出了步骤（拆不出来的情况单独测）。"""
    view = parse_bp_log(text, TEAM1, TEAM2)
    assert view is not None
    return view


class BpLogDisplayTests(unittest.TestCase):
    def test_generated_bo3_log_becomes_steps(self):
        view = _parse(GENERATED_BO3)

        self.assertEqual(view["roll"], {"t1": "39", "t2": "43", "winner": "t2"})
        self.assertEqual(view["order"]["team"], "t2")
        self.assertEqual(view["order"]["order"], "先手")
        self.assertEqual(
            [s["action"] for s in view["steps"]],
            ["ban", "ban", "pick", "pick", "ban", "ban", "left"],
        )
        self.assertEqual(
            view["steps"][2],
            {"num": 3, "team": "t2", "label": "T2", "action": "pick", "map": "Nuke"},
        )
        self.assertEqual(view["steps"][6]["map"], "Mirage")
        self.assertEqual(view["notes"], [])

    def test_old_side_lines_get_the_choosing_team(self):
        bo3 = _parse(GENERATED_BO3)
        # 选图方的对手选边：Nuke 是 T2 选的 → T1 选 T 方；Ancient 是 T1 选的 → T2 选 CT 方
        self.assertEqual(
            [(s["map"], s["team"], s["side"]) for s in bo3["sides"]],
            [("Nuke", "t1", "T"), ("Ancient", "t2", "CT")],
        )

        bo1 = _parse(GENERATED_BO1)
        # BO1 剩余图：最后一次禁图是 T1 → T2 选边
        self.assertEqual(
            [(s["map"], s["team"], s["side"]) for s in bo1["sides"]], [("Dust2", "t2", "CT")]
        )

    def test_new_side_line_names_the_team(self):
        view = _parse("3. U8 Pick Nuke\n选边: G8 为 Nuke 选择 CT 方")
        self.assertEqual(
            view["sides"], [{"team": "t2", "label": "G8", "map": "Nuke", "side": "CT"}]
        )

    def test_handwritten_log_keeps_unknown_lines_as_notes(self):
        view = _parse(HANDWRITTEN)

        self.assertEqual(view["notes"], ["t3-myh66等 t4-Matsubara Kanon等"])
        self.assertEqual(
            [(s["num"], s["label"], s["action"], s["map"]) for s in view["steps"]],
            [(1, "T3", "ban", "OP"), (2, "T4", "pick", "MIRAGE"), (3, "", "left", "NUKE")],
        )
        self.assertIsNone(view["steps"][0]["team"])

    def test_text_without_any_step_is_shown_as_is(self):
        self.assertIsNone(parse_bp_log("双方协商后直接打 Mirage", TEAM1, TEAM2))
        self.assertIsNone(parse_bp_log("", TEAM1, TEAM2))
        self.assertIsNone(parse_bp_log(None, TEAM1, TEAM2))


if __name__ == "__main__":
    unittest.main()
