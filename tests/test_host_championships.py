"""Managed event awards and published history in the original site."""

import unittest
from unittest.mock import patch

from services import bracket_service as bracket
from services.champion_service import player_championships, save_champion
from site_core.events import public, registration
from site_core.host import write
from site_core.matches import maps, operations, participants, results, statistics
from tests import test_host_operations_chain, test_host_prematch_chain
from utils.award_poster import generate_award_poster


class ManagedChampionshipTests(unittest.TestCase):
    def setUp(self):
        self.site = test_host_prematch_chain.HostPrematchChainTests()
        self.addCleanup(self.site.doCleanups)
        self.site.setUp()
        self.semi = self.site.prepare_through_host()
        self.db, self.actor, self.event = self.site.db, self.site.admin_id, self.site.event_id
        self.path = f"/admin/events/{self.event}/operations/championship"

    def _play(self, match, *, home_players=5):
        slot = maps.list_scheduled_maps(self.db, match)[0]["scheduled_map_id"]
        operations.authorize(self.db, match, self.actor)
        run = operations.observe_start(self.db, match, slot, source="director", evidence="现场开图")
        for row in self.db.execute(
            """SELECT l.*, p.side_key FROM map_run_lineups l JOIN match_participants p USING(match_participant_id)
               WHERE l.map_run_id=?""",
            (run,),
        ).fetchall():
            if row["side_key"] == "away" or row["roster_slot"] <= home_players:
                operations.record_participation(
                    self.db,
                    run,
                    row["player_id"],
                    row["match_participant_id"],
                    source="admin",
                    actor=self.actor,
                    reason="核对现场实际出场",
                )
        results.confirm_map(self.db, match, slot, run, 13, 7, source="admin", actor=self.actor)
        result = results.settle_series(self.db, match, actor=self.actor)
        return run, slot, result["series"]["settlement_id"]

    def test_award_uses_the_actual_five_from_the_final_and_freezes_the_result(self):
        site, db = self.site, self.db
        home = site.lineups[0]
        entrant = home["event_entrant_id"]
        control = site.admin.get(site.prefix).get_json()
        incoming = next(
            row["player_id"]
            for row in control["reserve_candidates"]
            if row["registration_origin"] == "independent_reserve"
        )
        outgoing = home["current_player_ids"][-1]
        with write(db):
            reservation = public.assign_reserve(
                db,
                self.event,
                entrant,
                incoming,
                expected_revision=control["formation_revision"],
                admin_id=self.actor,
                reason="确认候补",
                now=site.deadline + 1,
            )
            db.execute("UPDATE matches SET stage='胜者组决赛' WHERE id=?", (self.semi,))
            final = bracket.create_bracket_match(
                db,
                self.event,
                bo_format="BO1",
                stage="总决赛",
                actor=self.actor,
            )["match_id"]
            bracket.configure_bracket_link(db, self.semi, "winner", final, "home", actor=self.actor)
            bracket.configure_bracket_link(db, self.semi, "loser", final, "away", actor=self.actor)
            self._play(self.semi)
            public.replace_before_series(
                db,
                self.event,
                entrant,
                outgoing,
                incoming,
                expected_revision=reservation["formation_revision"],
                admin_id=self.actor,
                reason="决赛前换上已核准的候补",
                now=site.deadline + 2,
            )
            maps.sync_scheduled_maps(db, final, setup={"map1": "de_mirage"})
            participants.freeze_rosters(db, final, self.actor)
            db.execute(
                """UPDATE matches SET bp_state='{"status":"completed"}' WHERE id=?""", (final,)
            )
            run, slot, settlement = self._play(final, home_players=4)
            legacy_event = db.execute("INSERT INTO events(name) VALUES('旧届联调杯')").lastrowid
            club = db.execute("INSERT INTO teams(name) VALUES('旧届冠军俱乐部')").lastrowid
            save_champion(db, legacy_event, club)

        def get_status():
            return site.admin.get(self.path).get_json()

        payload = {
            "match_id": final,
            "settlement_id": settlement,
            "player_ids": [*home["current_player_ids"][:-1], incoming],
        }
        self.assertIn("五名", get_status()["blocked_reason"])
        self.assertEqual(site.post(site.admin, self.path, json=payload).status_code, 409)
        self.assertEqual(
            site.visitor.get(f"/api/front/events/{self.event}").get_json()["champions"], []
        )

        with write(db):
            home_side = db.execute(
                "SELECT match_participant_id FROM match_participants WHERE match_id=? AND side_key='home'",
                (final,),
            ).fetchone()[0]
            operations.record_participation(
                db,
                run,
                incoming,
                home_side,
                source="admin",
                actor=self.actor,
                reason="补证决胜局出场",
            )
        self.assertIsNone(get_status()["championship"])
        self.assertEqual(
            site.post(site.admin, self.path, json={**payload, "match_id": self.semi}).status_code,
            409,
        )
        self.assertEqual(site.admin.post(self.path, json=payload).status_code, 403)
        visitor = site.client(user_id=site.accounts[0])
        self.assertEqual(site.post(visitor, self.path, json=payload).status_code, 401)

        issued = site.post(site.admin, self.path, json=payload)
        self.assertEqual(issued.status_code, 201, issued.get_data(as_text=True))
        award = issued.get_json()["championship"]
        self.assertEqual((award["event_entrant_id"], award["club_id"]), (entrant, None))
        self.assertEqual([p["player_id"] for p in award["players"]], payload["player_ids"])
        duplicate = site.post(site.admin, self.path, json=payload)
        self.assertEqual(
            (duplicate.status_code, duplicate.get_json()["championship"]), (200, award)
        )
        self.assertTrue(duplicate.get_json()["duplicate"])

        with write(db):
            results.confirm_map(
                db,
                final,
                slot,
                run,
                7,
                13,
                source="admin",
                actor=self.actor,
                reason="复核图分后改判",
            )
            registration.archive_event(db, self.event, admin_id=self.actor, now=site.deadline + 300)
            db.execute("UPDATE players SET team_id=? WHERE id=?", (club, incoming))
        updated = get_status()
        self.assertTrue(updated["championship"]["needs_review"])
        self.assertNotEqual(updated["candidate"]["settlement_id"], settlement)
        repeated = site.post(site.admin, self.path, json=payload).get_json()
        self.assertTrue(repeated["duplicate"])
        self.assertEqual(repeated["championship"], updated["championship"])
        self.assertEqual(repeated["blocked_reason"], updated["blocked_reason"])
        revised = updated["candidate"]
        self.assertEqual(
            site.post(
                site.admin,
                self.path,
                json={
                    "match_id": final,
                    "settlement_id": revised["settlement_id"],
                    "player_ids": [p["player_id"] for p in revised["players"]],
                },
            ).status_code,
            409,
        )
        self.assertEqual([r["event_id"] for r in player_championships(db, incoming)], [self.event])
        self.assertEqual(player_championships(db, outgoing), [])

        (champion,) = site.visitor.get(f"/api/front/events/{self.event}").get_json()["champions"]
        self.assertEqual(
            (champion["id"], champion["url"], champion["name"], champion["players"]),
            (None, site.event_url, award["team_name"], 5),
        )
        profile = site.visitor.get(f"/players/{incoming}").get_data(as_text=True)
        self.assertIn(
            site.event_url, profile.split('id="trophies"', 1)[1].split("</section>", 1)[0]
        )
        hall = site.visitor.get("/awards")
        self.assertEqual(hall.status_code, 200)
        self.assertIn("旧届冠军俱乐部", hall.get_data(as_text=True))
        self.assertRegex(
            hall.get_data(as_text=True),
            rf'(?s)<a class="award-champion" href="{site.event_url}">(?:(?!</a>).)*{award["team_name"]}</span>',
        )

    def test_stage_label_cannot_override_the_bracket_evidence(self):
        with write(self.db):
            self.db.execute("UPDATE matches SET stage='决赛' WHERE id=?", (self.semi,))
            next_match = bracket.create_bracket_match(
                self.db,
                self.event,
                bo_format="BO1",
                stage="第三名赛",
                actor=self.actor,
            )["match_id"]
            bracket.configure_bracket_link(
                self.db,
                self.semi,
                "loser",
                next_match,
                "home",
                actor=self.actor,
            )
            self._play(self.semi)
        preview = self.site.admin.get(self.path).get_json()
        self.assertIn("下游签位", preview["blocked_reason"])
        self.assertIsNone(preview["candidate"])

    def test_managed_personal_awards_use_formal_appearances_and_an_explicit_order(self):
        site, db = self.site, self.db
        path = f"/admin/events/{self.event}/operations/player-awards"
        mvp, evp_home, _, _, unplayed = site.lineups[0]["current_player_ids"]
        favorite, evp_away = site.lineups[1]["current_player_ids"][:2]
        payload = {"mvp_player_id": mvp, "evp_player_ids": [evp_away, evp_home, evp_away]}
        self.assertEqual(site.post(site.admin, path, json=payload).status_code, 409)
        with write(db):
            db.execute("UPDATE matches SET stage='决赛' WHERE id=?", (self.semi,))
            run, _, settlement = self._play(self.semi, home_players=4)
            for revision, (player, rating) in enumerate(((mvp, 1.25), (favorite, 1.9))):
                updated = statistics.apply_fields(
                    db,
                    run,
                    player,
                    "all",
                    {"rounds": 20, "rating": rating},
                    source="admin",
                    actor=self.actor,
                    reason="按赛后原始记录核对",
                    expected=revision,
                    confirm=True,
                )
                self.assertTrue(updated["applied"])
            match_medal = db.execute(
                """INSERT INTO player_medals(player_id,type,event_id,match_id)
                   VALUES(?,'MVP',?,?)""",
                (favorite, self.event, self.semi),
            ).lastrowid

        preview = site.admin.get(path).get_json()
        self.assertFalse(preview["awards"])
        self.assertIsNone(preview["blocked_reason"])
        candidates = {row["player_id"]: row for row in preview["candidates"]}
        self.assertNotIn(unplayed, candidates)
        self.assertEqual(candidates[mvp]["event_entrant_id"], site.lineups[0]["event_entrant_id"])
        self.assertEqual(site.admin.post(path, json=payload).status_code, 403)
        self.assertEqual(
            site.post(site.client(user_id=site.accounts[0]), path, json=payload).status_code, 401
        )
        self.assertEqual(
            site.post(site.admin, path, json={**payload, "mvp_player_id": unplayed}).status_code,
            409,
        )

        published = site.post(site.admin, path, json=payload)
        self.assertEqual(published.status_code, 200, published.get_data(as_text=True))
        awards = published.get_json()["awards"]
        self.assertEqual(
            [(r["player_id"], r["evp_rank"]) for r in awards],
            [(mvp, 0), (evp_away, 1), (evp_home, 2)],
        )

        reordered = site.post(
            site.admin, path, json={"mvp_player_id": mvp, "evp_player_ids": [evp_home, evp_away]}
        )
        self.assertEqual(reordered.status_code, 200)
        after = reordered.get_json()["awards"]
        self.assertEqual(
            [(r["player_id"], r["evp_rank"]) for r in after],
            [(mvp, 0), (evp_home, 1), (evp_away, 2)],
        )
        self.assertCountEqual(
            [(r["id"], r["created_at"]) for r in after],
            [(r["id"], r["created_at"]) for r in awards],
        )
        self.assertEqual(
            db.execute("SELECT match_id FROM player_medals WHERE id=?", (match_medal,)).fetchone()[0],
            self.semi,
        )
        self.assertEqual(results.read_results(db, self.semi)["series"]["settlement_id"], settlement)
        detail = site.visitor.get(f"/api/front/events/{self.event}").get_json()
        self.assertFalse(detail["champions"])
        self.assertEqual(
            [(r["player_id"], r["rank"]) for r in detail["awards"] if r["player_id"] != favorite],
            [(mvp, 0), (evp_home, 1), (evp_away, 2)],
        )
        self.assertIn(favorite, [r["player_id"] for r in detail["awards"]])

        with patch(
            "services.award_service.generate_award_poster", wraps=generate_award_poster
        ) as render:
            poster = site.visitor.get(f"/events/{self.event}/mvp-poster.png")
        self.assertEqual((poster.status_code, poster.mimetype), (200, "image/png"))
        self.assertTrue(poster.data.startswith(b"\x89PNG\r\n\x1a\n"))
        _, player, _, stats, cards, _ = render.call_args.args
        self.assertEqual(
            (player["team_name"], stats["rating"], stats["maps"]),
            (candidates[mvp]["team_name"], 1.25, 1),
        )
        self.assertEqual((cards[0]["score_for"], cards[0]["score_against"]), (13, 7))
        self.assertEqual(
            site.visitor.get(f"/events/{self.event}/award-poster/MVP/{unplayed}.png").status_code,
            404,
        )


class TechnicalChampionshipEvidenceTests(unittest.TestCase):
    def test_two_actual_lineups_in_one_final_require_review(self):
        chain = test_host_operations_chain.HostOperationsChainTests()
        self.addCleanup(chain.doCleanups)
        chain.setUp()
        case = chain.prepare_bo3()
        site, match, event = chain.site, case["match_id"], case["event_id"]
        with write(site.db):
            site.db.execute("UPDATE matches SET stage='总决赛' WHERE id=?", (match,))
        chain.complete_bo3(case)
        preview = site.admin.get(f"/admin/events/{event}/operations/championship").get_json()
        self.assertIn("不同获胜方成员", preview["blocked_reason"])
        self.assertIsNone(preview["championship"])
