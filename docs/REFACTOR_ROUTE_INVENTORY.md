# 后端功能与路由清单

由 `scripts/audit_backend_contracts.py` 从实际 Flask 注册结果生成；不会初始化或修改数据库。
现有前端是 Jinja 页面与浏览器局部数据更新并用，不是单独的 SPA。页面布局保留。

| 方法 | 路径 | 处理模块与函数 |
| --- | --- | --- |
| GET | `/` | `routes.home.index` |
| POST | `/account/complete-profile` | `routes.auth.complete_account_profile` |
| GET | `/admin` | `blueprints.admin_core.admin_dashboard` |
| GET | `/admin/` | `blueprints.admin_core.admin_dashboard` |
| GET | `/admin/awards/poster` | `blueprints.admin_operations.admin_award_poster` |
| GET | `/admin/awards/poster.png` | `blueprints.admin_operations.admin_award_poster_image` |
| GET | `/admin/backup/download` | `blueprints.admin_operations.admin_backup_download` |
| GET | `/admin/events` | `blueprints.admin_events.admin_events` |
| GET, POST | `/admin/events/<int:event_id>/bracket` | `blueprints.admin_events.admin_event_bracket` |
| POST | `/admin/events/<int:event_id>/bracket/api/save` | `blueprints.admin_events.bracket_api_save` |
| GET | `/admin/events/<int:event_id>/bracket/api/teams` | `blueprints.admin_events.bracket_api_teams` |
| GET, POST | `/admin/events/add` | `blueprints.admin_events.admin_events_add` |
| POST | `/admin/events/delete/<int:event_id>` | `blueprints.admin_events.admin_events_delete` |
| GET, POST | `/admin/events/edit/<int:event_id>` | `blueprints.admin_events.admin_events_edit` |
| GET | `/admin/feedback` | `blueprints.admin_operations.admin_feedback` |
| POST | `/admin/feedback/<int:fb_id>/status` | `blueprints.admin_operations.admin_feedback_status` |
| GET | `/admin/live` | `blueprints.admin_operations.admin_live_status` |
| GET, POST | `/admin/login` | `blueprints.admin_core.admin_login` |
| GET | `/admin/logout` | `blueprints.admin_core.admin_logout` |
| GET | `/admin/matches` | `blueprints.admin_matches.admin_matches` |
| POST | `/admin/matches/<int:match_id>/complete` | `blueprints.admin_matches.admin_match_complete` |
| GET, POST | `/admin/matches/<int:match_id>/import-demo` | `blueprints.admin_matches.admin_import_demo` |
| POST | `/admin/matches/<int:match_id>/reopen` | `blueprints.admin_matches.admin_match_reopen` |
| GET, POST | `/admin/matches/<int:match_id>/stats` | `blueprints.admin_matches.admin_match_stats` |
| GET, POST | `/admin/matches/add` | `blueprints.admin_matches.admin_matches_add` |
| POST | `/admin/matches/delete/<int:match_id>` | `blueprints.admin_matches.admin_matches_delete` |
| GET, POST | `/admin/matches/edit/<int:match_id>` | `blueprints.admin_matches.admin_matches_edit` |
| GET | `/admin/news` | `blueprints.admin_news.admin_news` |
| GET, POST | `/admin/news/add` | `blueprints.admin_news.admin_news_add` |
| POST | `/admin/news/delete/<int:news_id>` | `blueprints.admin_news.admin_news_delete` |
| GET, POST | `/admin/news/edit/<int:news_id>` | `blueprints.admin_news.admin_news_edit` |
| GET | `/admin/nicknames` | `blueprints.admin_operations.admin_nicknames` |
| POST | `/admin/nicknames/merge` | `blueprints.admin_operations.admin_nicknames_merge` |
| GET | `/admin/players` | `blueprints.admin_catalog.admin_players` |
| GET, POST | `/admin/players/add` | `blueprints.admin_catalog.admin_players_add` |
| POST | `/admin/players/delete/<int:player_id>` | `blueprints.admin_catalog.admin_players_delete` |
| GET, POST | `/admin/players/edit/<int:player_id>` | `blueprints.admin_catalog.admin_players_edit` |
| GET, POST | `/admin/players/password/<int:player_id>` | `blueprints.admin_catalog.admin_player_password` |
| POST | `/admin/players/refresh-playtime` | `blueprints.admin_catalog.admin_players_refresh_playtime` |
| GET | `/admin/registrations` | `blueprints.admin_core.registration_reviews` |
| POST | `/admin/registrations/<int:user_id>/<action>` | `blueprints.admin_core.review_registration` |
| POST | `/admin/registrations/create` | `blueprints.admin_core.create_registration` |
| GET | `/admin/teams` | `blueprints.admin_catalog.admin_teams` |
| GET, POST | `/admin/teams/add` | `blueprints.admin_catalog.admin_teams_add` |
| POST | `/admin/teams/delete/<int:team_id>` | `blueprints.admin_catalog.admin_teams_delete` |
| GET, POST | `/admin/teams/edit/<int:team_id>` | `blueprints.admin_catalog.admin_teams_edit` |
| GET | `/admin/top10` | `blueprints.admin_operations.admin_top10` |
| POST | `/admin/top10/save` | `blueprints.admin_operations.admin_top10_save` |
| POST | `/admin/upload/image` | `blueprints.admin_core.upload_image` |
| POST | `/api/bp/<int:match_id>/action` | `routes.bp.bp_api_action` |
| POST | `/api/bp/<int:match_id>/heartbeat` | `routes.bp.bp_api_heartbeat` |
| POST | `/api/bp/<int:match_id>/reset` | `routes.bp.bp_api_reset` |
| POST | `/api/bp/<int:match_id>/seat/release` | `routes.bp.bp_api_release_seat` |
| GET | `/api/bp/<int:match_id>/state` | `routes.bp.bp_api_state` |
| POST | `/api/bp/<int:match_id>/undo` | `routes.bp.bp_api_undo` |
| GET | `/api/broadcast/current` | `routes.broadcast.api_broadcast_current` |
| GET | `/api/broadcast/events` | `routes.broadcast.api_broadcast_events` |
| GET | `/api/broadcast/events/<int:event_id>` | `routes.broadcast.api_broadcast_event` |
| GET | `/api/broadcast/matches` | `routes.broadcast.api_broadcast_matches` |
| GET | `/api/broadcast/matches/<int:match_id>` | `routes.broadcast.api_broadcast_match` |
| GET | `/api/broadcast/matches/<int:match_id>/connection-test` | `routes.live_ingest.broadcast_connection_test` |
| POST | `/api/broadcast/matches/<int:match_id>/live` | `routes.live_ingest.broadcast_gsi_receiver` |
| POST | `/api/broadcast/matches/<int:match_id>/map-result` | `routes.live_ingest.broadcast_map_result_receiver` |
| POST | `/api/feedback/submit` | `routes.feedback.feedback_submit` |
| GET | `/api/front/dashboard` | `routes.front_api.api_front_dashboard` |
| GET | `/api/front/events` | `routes.front_api.api_front_events` |
| GET | `/api/front/events/<int:event_id>` | `routes.front_api.api_front_event_detail` |
| GET | `/api/front/features` | `routes.front_api.api_front_features` |
| GET | `/api/front/forum` | `routes.front_api.api_front_forum` |
| GET | `/api/front/home` | `routes.front_api.api_front_home` |
| GET | `/api/front/matches` | `routes.front_api.api_front_matches` |
| GET | `/api/front/matches/<int:match_id>` | `routes.front_api.api_front_match_detail` |
| GET | `/api/front/news` | `routes.front_api.api_front_news` |
| GET | `/api/front/news/<int:news_id>` | `routes.front_api.api_front_news_detail` |
| GET | `/api/front/notifications` | `routes.front_api.api_front_notifications` |
| GET | `/api/front/players` | `routes.front_api.api_front_players` |
| GET | `/api/front/players/<int:player_id>` | `routes.front_api.api_front_player_detail` |
| GET | `/api/front/predictions` | `routes.front_api.api_front_predictions` |
| GET | `/api/front/results` | `routes.front_api.api_front_results` |
| GET | `/api/front/stats/overview` | `routes.front_api.api_front_stats_overview` |
| GET | `/api/front/teams` | `routes.front_api.api_front_teams` |
| POST | `/api/gotv/stats` | `routes.live_ingest.gotv_stats_receiver` |
| POST | `/api/gsi/receive` | `routes.live_ingest.gsi_receiver` |
| POST | `/api/guess-player/multiplayer/<room_code>/guess` | `routes.guess_player.guess_player_multiplayer_guess` |
| GET | `/api/guess-player/multiplayer/<room_code>/state` | `routes.guess_player.guess_player_multiplayer_state` |
| GET | `/api/live/<int:match_id>` | `routes.live.api_live_match` |
| GET | `/api/search` | `routes.search.api_search` |
| GET | `/auth/csrf-token` | `routes.auth.current_csrf_token` |
| POST | `/auth/email/send-code` | `routes.auth.send_registration_email_code` |
| POST | `/auth/email/verify-code` | `routes.auth.verify_registration_email_code` |
| GET | `/auth/steam/callback` | `routes.auth.steam_auth_callback` |
| GET | `/auth/steam/start` | `routes.auth.steam_auth_start` |
| GET | `/awards` | `routes.stats.awards_page` |
| GET | `/bp/<int:match_id>` | `routes.bp.bp_room` |
| POST | `/bp/<int:match_id>/verify` | `routes.bp.bp_verify` |
| GET | `/captcha/image` | `routes.auth.captcha_image` |
| GET | `/captcha/reload` | `routes.auth.reload_captcha` |
| GET, POST | `/change-password` | `routes.auth.change_password` |
| POST | `/comment/<target_type>/<int:target_id>` | `routes.comments.add_comment` |
| POST | `/comment/delete/<int:comment_id>` | `routes.comments.delete_comment` |
| POST | `/comment/like/<int:comment_id>` | `routes.comments.comment_like` |
| GET | `/dashboard` | `routes.home.dashboard` |
| GET | `/events` | `routes.events.events_list` |
| GET | `/events/<event_id>` | `routes.events.event_detail` |
| GET | `/events/<event_id>/stats` | `routes.events.event_stats` |
| GET | `/events/<int:event_id>/award-poster/<award_type>/<int:player_id>.png` | `routes.events.event_award_poster` |
| POST | `/events/<int:event_id>/individual-registration/<int:entry_id>/remove` | `routes.events.event_remove_individual_registration` |
| POST | `/events/<int:event_id>/individual-registration/finalize` | `routes.events.event_finalize_individual_teams` |
| POST | `/events/<int:event_id>/individual-registration/randomize` | `routes.events.event_randomize_individual_teams` |
| POST | `/events/<int:event_id>/individual-registration/withdraw` | `routes.events.event_withdraw_individual` |
| POST | `/events/<int:event_id>/join/<int:reg_id>/<int:slot>` | `routes.events.event_join_slot` |
| POST | `/events/<int:event_id>/leave/<int:reg_id>/<int:slot>` | `routes.events.event_leave_slot` |
| GET | `/events/<int:event_id>/mvp-poster.png` | `routes.events.event_mvp_poster` |
| POST | `/events/<int:event_id>/register` | `routes.events.event_register` |
| POST | `/events/<int:event_id>/register-individual` | `routes.events.event_register_individual` |
| POST | `/events/<int:event_id>/register-substitute` | `routes.events.event_register_substitute` |
| POST | `/events/<int:event_id>/registrations/<int:reg_id>/dissolve` | `routes.events.event_registration_dissolve` |
| POST | `/events/<int:event_id>/registrations/<int:reg_id>/logo` | `routes.events.event_registration_upload_logo` |
| POST | `/events/<int:event_id>/registrations/<int:reg_id>/logo/remove` | `routes.events.event_registration_remove_logo` |
| POST | `/events/<int:event_id>/registrations/<int:reg_id>/rename` | `routes.events.event_registration_rename` |
| POST | `/events/<int:event_id>/registrations/<int:reg_id>/slots/<int:slot>/captain` | `routes.events.event_registration_transfer_captain` |
| POST | `/events/<int:event_id>/registrations/<int:reg_id>/slots/<int:slot>/remove` | `routes.events.event_registration_remove_member` |
| POST | `/events/<int:event_id>/registrations/<int:reg_id>/slots/<int:slot>/update` | `routes.events.event_registration_update_member` |
| GET | `/favicon.ico` | `web_app.favicon` |
| GET | `/forum` | `routes.forum.forum_index` |
| GET | `/forum/t/<int:thread_id>` | `routes.forum.forum_thread` |
| GET, POST | `/forum/t/<int:thread_id>/edit` | `routes.forum.forum_edit_thread` |
| POST | `/forum/t/<int:thread_id>/manage` | `routes.forum.forum_manage_thread` |
| POST | `/forum/t/<int:thread_id>/reply` | `routes.forum.forum_thread_reply` |
| GET, POST | `/forum/thread/new` | `routes.forum.forum_new_thread` |
| GET | `/games` | `routes.games.games_page` |
| GET | `/guess-player` | `routes.guess_player.guess_player_page` |
| POST | `/guess-player` | `routes.guess_player.guess_player_submit` |
| GET | `/guess-player/multiplayer` | `routes.guess_player.guess_player_multiplayer_page` |
| GET | `/guess-player/multiplayer/<room_code>` | `routes.guess_player.guess_player_multiplayer_room` |
| POST | `/guess-player/multiplayer/create` | `routes.guess_player.guess_player_multiplayer_create` |
| POST | `/guess-player/multiplayer/join` | `routes.guess_player.guess_player_multiplayer_join` |
| GET | `/guess-player/practice` | `routes.guess_player.guess_player_practice_page` |
| POST | `/guess-player/practice` | `routes.guess_player.guess_player_practice_submit` |
| POST | `/guess-player/practice/new` | `routes.guess_player.guess_player_practice_new` |
| GET | `/healthz` | `web_app.healthz` |
| GET, POST | `/login` | `routes.auth.user_login` |
| GET | `/logout` | `routes.auth.user_logout` |
| GET | `/map-quiz` | `routes.map_quiz.map_quiz_page` |
| POST | `/map-quiz` | `routes.map_quiz.map_quiz_submit` |
| GET | `/map-quiz/image/<question_key>` | `routes.map_quiz.map_quiz_image` |
| GET | `/map-quiz/practice` | `routes.map_quiz.map_quiz_practice_page` |
| POST | `/map-quiz/practice` | `routes.map_quiz.map_quiz_practice_submit` |
| POST | `/map-quiz/practice/new` | `routes.map_quiz.map_quiz_practice_new` |
| GET | `/matches` | `routes.matches.matches_list` |
| GET | `/matches/<int:match_id>/live` | `routes.matches.match_live` |
| GET | `/matches/<int:match_id>/report` | `routes.match_assets.match_report` |
| GET | `/matches/<slug>` | `routes.matches.match_detail` |
| GET | `/matches/<slug>/detailed` | `routes.matches.match_detailed_stats` |
| GET | `/matches/<slug>/download-demo` | `routes.match_assets.download_demo` |
| GET | `/matches/<slug>/poster` | `routes.match_assets.match_poster` |
| GET | `/matches/<slug>/stats` | `routes.matches.match_detail` |
| POST | `/matches/<slug>/vote` | `routes.matches.match_vote` |
| GET | `/news` | `routes.news.news_list` |
| GET | `/news/<int:news_id>` | `routes.news.news_detail` |
| GET | `/notifications` | `routes.notifications.notifications_list` |
| POST | `/notifications/read-all` | `routes.notifications.notification_read_all` |
| POST | `/notifications/read/<int:notif_id>` | `routes.notifications.notification_read` |
| GET | `/notifications/unread-count` | `routes.notifications.notification_unread_count` |
| GET | `/player-bingo` | `routes.player_bingo.player_bingo_page` |
| POST | `/player-bingo` | `routes.player_bingo.player_bingo_submit` |
| GET | `/player-bingo/practice` | `routes.player_bingo.player_bingo_practice_page` |
| POST | `/player-bingo/practice` | `routes.player_bingo.player_bingo_practice_submit` |
| POST | `/player-bingo/practice/new` | `routes.player_bingo.player_bingo_practice_new` |
| GET | `/players` | `routes.players.players_list` |
| GET | `/players/<int:player_id>` | `routes.players.player_detail` |
| POST | `/players/<int:player_id>/remark` | `routes.players.player_private_remark` |
| GET | `/players/compare` | `routes.players.player_compare` |
| GET | `/predictions` | `routes.stats.predictions_page` |
| GET, POST | `/profile` | `routes.auth.user_profile` |
| GET, POST | `/register` | `routes.auth.user_register` |
| GET | `/resources/<path:filename>` | `web_app.serve_resource` |
| GET | `/resources/fonts/<path:filename>` | `web_app.serve_font_resource` |
| GET | `/resources/maps/<path:filename>` | `web_app.serve_map_resource` |
| GET | `/results` | `routes.matches.results_list` |
| GET | `/robots.txt` | `web_app.robots_txt` |
| GET | `/search` | `routes.search.search` |
| GET | `/sitemap.xml` | `routes.sitemap.sitemap` |
| GET | `/static/<path:filename>` | `flask.app.<lambda>` |
| GET | `/stats` | `routes.stats.stats_page` |
| GET | `/stats/overview/<section>` | `routes.stats.stats_overview_detail` |
| GET | `/stats/players/<int:player_id>` | `routes.players.player_stats_detail` |
| GET | `/teams` | `routes.stats.teams_list` |
| GET | `/teams/<int:team_id>` | `routes.stats.team_detail` |

## 模块覆盖

| 模块 | 地址数 |
| --- | ---: |
| `blueprints.admin_catalog` | 10 |
| `blueprints.admin_core` | 8 |
| `blueprints.admin_events` | 7 |
| `blueprints.admin_matches` | 8 |
| `blueprints.admin_news` | 4 |
| `blueprints.admin_operations` | 10 |
| `flask.app` | 1 |
| `routes.auth` | 13 |
| `routes.bp` | 8 |
| `routes.broadcast` | 5 |
| `routes.comments` | 3 |
| `routes.events` | 21 |
| `routes.feedback` | 1 |
| `routes.forum` | 6 |
| `routes.front_api` | 17 |
| `routes.games` | 1 |
| `routes.guess_player` | 11 |
| `routes.home` | 2 |
| `routes.live` | 1 |
| `routes.live_ingest` | 5 |
| `routes.map_quiz` | 6 |
| `routes.match_assets` | 3 |
| `routes.matches` | 7 |
| `routes.news` | 2 |
| `routes.notifications` | 4 |
| `routes.player_bingo` | 5 |
| `routes.players` | 5 |
| `routes.search` | 2 |
| `routes.sitemap` | 1 |
| `routes.stats` | 6 |
| `web_app` | 6 |
