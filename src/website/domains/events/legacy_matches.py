"""Read old match evidence alongside canonical match participants; never change a match."""


def has_active_play(conn, event_id, registration_id):
    # A scheduled time, a frozen ten or completed BP is not evidence of actual play.
    scores = " OR ".join(f"m.map{slot}_t{side}>0" for slot in range(1, 6) for side in (1, 2))
    return (
        conn.execute(
            f"""SELECT 1 FROM matches m WHERE m.event_id=?
             AND COALESCE(m.status,'') NOT IN ('completed','cancelled')
             AND ((SELECT count(*) FROM match_participants WHERE match_id=m.id)<2 OR EXISTS
                 (SELECT 1 FROM match_participants p JOIN event_entrants e USING(event_entrant_id,event_id)
                  WHERE p.match_id=m.id AND e.registration_id=?))
             AND (m.status IN ('live','ongoing') OR m.team1_score>0 OR m.team2_score>0 OR {scores} OR EXISTS
                 (SELECT 1 FROM match_stats s WHERE s.match_id=m.id AND COALESCE(s.data_status,'final')='final'))
             LIMIT 1""",
            (event_id, registration_id),
        ).fetchone()
        is not None
    )


def has_unfinished_binding(conn, event_id, registration_id, entrant_id):
    return (
        conn.execute(
            """SELECT 1 FROM matches m WHERE m.event_id=? AND COALESCE(m.status,'') NOT IN ('completed','cancelled')
        AND (m.team1_registration_id=? OR m.team2_registration_id=? OR EXISTS
          (SELECT 1 FROM match_participants p WHERE p.match_id=m.id AND p.event_entrant_id=?))""",
            (event_id, registration_id, registration_id, entrant_id),
        ).fetchone()
        is not None
    )
