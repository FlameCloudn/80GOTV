"""公开选手身份：网站账号优先于占位记录，私人备注由展示层按阅读者应用。"""

from src.website.domains.identity.accounts import steam_account_source

ACCOUNT_JOIN = f"""
    LEFT JOIN users linked ON linked.id=(
        SELECT a.id {steam_account_source("p.steam_id")}
    )
"""

IDENTITY_FIELDS = """
    linked.id AS linked_user_id,
    COALESCE(linked.is_bashizhong_student, p.is_bashizhong_student) AS managed_is_bashizhong_student,
    CASE WHEN COALESCE(linked.is_bashizhong_student, p.is_bashizhong_student, 1) <> 0
         THEN COALESCE(NULLIF(TRIM(linked.group_username), ''),
                       NULLIF(TRIM(p.group_username_override), ''), '')
         ELSE '' END AS group_username
"""


def player_profile(conn, player_id: int):
    return conn.execute(
        f"""SELECT p.*, t.name AS team_name, t.short_name AS team_short, t.logo AS team_logo,
                   {IDENTITY_FIELDS}, COALESCE(linked.is_cheater, 0) AS is_cheater
            FROM players p {ACCOUNT_JOIN} LEFT JOIN teams t ON t.id=p.team_id WHERE p.id=?""",
        (player_id,),
    ).fetchone()
