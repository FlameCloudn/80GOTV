# 比赛、对阵、BP 与直播一致性审查

日期：2026-10-26。

## 工作边界

- 所有改动仅位于 `E:\Code\Projects\80GOTV\backend_refactor_20261026`，没有修改父目录原项目。
- 基线为 `bca519e`；原始源码保留在 `backups/source-baseline-bca519e.zip`。
- 本分工没有读取或改写真实比赛数据库，没有使用公网、真实导播、真实 GSI 会话或生产密钥。
- 测试只使用 `tests/__init__.py` 隔离后的临时数据库；`TMP/TEMP` 都指向本副本的 `output/tmp-match`。
- 没有提交、推送、部署、重启网站，也没有删除用户文件。

## 审查范围

主要修改：

- `services/match_service.py`：BO1/BO3/BO5 结果、结束前校验、积分重核、只读预测榜单。
- `services/bracket_service.py`：4/8 队单败与双败、参赛方来源、历史结果联动、并发生成、删除后的对阵状态。
- `utils/match_utils.py`：地图胜场的 BO 上限。
- `utils/bp_manager.py`：先后手阶段、地图别名重复、旧状态安全升级。
- `routes/bp.py`：参赛名单权限、口令验证、操作席、并发、撤回与重置。
- `blueprints/admin_matches.py`：结束、重新开启、普通编辑、删除与积分/对阵一起保存或回退。
- `blueprints/admin_events.py`：普通 JSON 表单和接口保存的一致校验、失败页面上下文。
- `services/live_service.py`：直播数字校验、导播统计解析、未确认地图标记、坐标处理。
- `routes/live_ingest.py`：GSI、GOTV、导播结算的校验、身份、地图、重复请求和整次保存。
- `routes/live.py`：换边身份与非法旧状态/无穷计时的只读容错。

另外跟踪了 `routes/matches.py` 中投票、公开比赛状态和赛果详情的相关调用，以及 `routes/broadcast.py` 中 BP 开局 CT 身份的输出。没有改动它们的页面布局或上游协议。

## 已确认并修复

| 问题 | 原因与修复 | 对应暴露/回归测试 |
| --- | --- | --- |
| BO3 的 0:0、1:0、2:2、3:0、负数也能点结束 | 原结束接口直接改状态；统一校验恰好达到所需胜场，取消比赛不能直接结束。普通编辑切到 completed 也走相同检查。 | `test_incomplete_and_impossible_series_cannot_be_completed`、`test_regular_editor_cannot_bypass_completion_validation` |
| 合理手工赛果依赖不必要的地图详情 | 保留手工录入能力；1:0、2:0/2:1、3:0/3:1/3:2 只需合法总胜场，不强制 Demo 或逐图数据。 | `test_valid_manual_series_results_can_complete_without_map_details` |
| BO1/BO3 把高槽位残留比分也算进去 | 地图计算没有按 BO 裁剪；现在限定有效槽位，Demo 与导播复用同一计算函数。 | `test_map_wins_ignore_slots_outside_bo_limit` |
| 完赛后改分，旧预测积分一直保留 | 旧函数只查询 scored=0；现在按当前合法结果覆盖分数，而不是累加。重新开启、取消、非法结果会撤回旧分。 | `test_predictions_follow_corrected_results_without_accumulating_points`、`test_cancelled_prediction_points_are_revoked_when_explicitly_reconciled` |
| 公开预测页读取时顺带改数据库 | 提供只读 `get_prediction_leaderboard`，按当前合法赛果直接生成榜单；它不改 votes、matches 或缓存。两个 GET 路由由主分工接入。 | `test_read_only_prediction_leaderboard_uses_current_result_without_writing_points` 用 `total_changes` 和原积分字段确认零写入 |
| 预测 API 漏掉零票比赛，且与 HTML 的即将进行列表不一致 | 将已有 HTML 的 LEFT JOIN、upcoming、未来/NULL 时间、票数和时间排序规则原样提取为 `get_prediction_upcoming_matches`，由两个路由共同读取，不另造规则。 | `test_prediction_upcoming_list_uses_the_existing_html_rules_without_writes` |
| 未完整获胜也会晋级 | 对阵以前只比较比分大小；现在只使用统一 BO 完赛判定。 | `test_incomplete_completed_series_never_advances` |
| 改历史结果后，已经开打的下一场仍保留旧队伍 | 原实现静默跳过非 upcoming；现在先验证整张对阵来源，再写入。下游已有比分、BP、开赛状态，或被替换那侧已有锁定名单时，整次阻止并给出中文原因。 | `test_changed_result_is_rejected_if_next_match_already_started`、`test_reopening_is_atomic_when_downstream_already_has_bp`、`test_historical_result_cannot_replace_a_side_with_a_locked_roster` |
| 过宽的名单保护会阻止另一边正常晋级 | 名单检查只针对实际被替换的那一侧，不拦住对方正常补入。 | `test_roster_of_an_unchanged_side_does_not_block_the_other_winner_advancing` |
| 编辑首轮种子看似成功，实际队伍未变 | 旧刷新先用数据库队伍覆盖提交的种子；现在以明确种子来源解析未开始的参赛方。 | `test_changed_seed_is_applied_to_unstarted_matches` |
| 对阵可绑定其他赛事、重复比赛或循环来源 | 保存和刷新都检查赛事归属、重复绑定、来源格式与循环；普通 JSON 表单不能绕过。 | `test_foreign_event_match_binding_is_never_updated`、`test_raw_bracket_form_cannot_store_cross_event_bindings` |
| 两次同时生成可能多造一场比赛 | 两边先读到“没有可复用比赛”，随后各自创建；生成前取得写入锁，再读当前对阵。 | `test_two_concurrent_builds_do_not_create_duplicate_matches` 红测确实生成 4 场而不是 3 场，修复后保持 3 场 |
| 删除赛果后，下一场仍显示原晋级队伍 | 删除入口没有刷新对阵；现在同事务清除未开始下游的失效参赛方，并去掉已不存在的绑定和比分。已经准备/开始的下游仍会阻止删除并回退。 | `test_deleting_a_result_clears_unstarted_downstream_assignment` |
| 对阵 sections 与旧 rounds 字段比分不一致 | JSON 往返后两份结构不再共享对象；刷新后重建兼容 rounds。 | `test_legacy_rounds_and_sections_keep_identical_live_scores` |
| Roll 胜方没选先后手也能禁/选图 | get_team_for_step 将空选择误当后手；现在明确拒绝。 | `test_ban_requires_first_order_choice`、`test_pick_requires_first_order_choice_even_without_initial_bans` |
| 未入本场名单的长期队员也可操作 BP | 原权限最后回退长期队伍，不管本场名单是否存在；现在名单优先，只有名单为空的旧比赛才回退。 | `test_locked_roster_excludes_unselected_permanent_teammates`、`test_legacy_empty_roster_still_uses_permanent_membership` |
| BP 心跳覆盖刚完成的操作，旧状态升级覆盖新状态 | 整段 JSON 先读后写、没有写入锁；现在写入口读前锁定，旧状态升级使用原值条件更新。 | `test_heartbeat_cannot_overwrite_a_concurrent_bp_action`、`test_old_state_upgrade_cannot_overwrite_a_newer_committed_action` |
| 失败请求也会保存部分 BP 升级 | 中途 commit 已移除，拒绝的版本和失败操作全部回退。 | `test_invalid_bp_request_does_not_commit_state_upgrade` |
| 比赛有比分/已结束仍可撤回或重置 BP | 各入口缺少一致锁定；现在结束、取消或已有比分均不能重置、撤回、再禁选。结束比赛的心跳也不再写入。 | `test_bp_undo_is_locked_after_match_has_scores_or_is_closed`、`test_bp_reset_is_locked_after_match_has_scores`、`test_closed_match_heartbeat_does_not_modify_bp` |
| 重置完成 BP 后旧地图还在 | 只清 bp_state；现在清掉该完成 BP 生成的地图/选图方/开局拼刀字段，同时保留配置图池。 | `test_reset_completed_bp_clears_only_its_generated_maps` |
| 修改共享口令后旧浏览器仍可操作 | 会话原来只保存 True；现在验证绑定当前口令版本的不可逆标记。旧布尔验证会要求重新验证一次。 | `test_password_change_invalidates_an_older_bp_verification` |
| Dust2 和 de_dust2 可重复入池 | 只按展示字符串去重；现在使用同一地图存储键去重，保存完成结果时也检查重复。 | `test_map_aliases_cannot_put_the_same_real_map_in_a_pool_twice` |
| 直播 NaN/无穷大/文本/小数被夹成真实统计 | 原数字解析把错误值变 0，把异常值夹成上限；现在拒绝非法数、非整数计数、负数和不合理范围，失败不写入。 | `test_nonfinite_fractional_negative_and_text_scores_are_rejected_without_writes`、`test_invalid_player_numbers_are_not_clamped_into_real_stats`、`test_secondary_relay_metrics_are_validated_too` |
| 缺少助攻也生成 Impact/Rating | 缺值以前被伪装成 0；现在保留 None，缺必要数据不猜评分。新导播/GOTV 总评分与新 Demo 使用同一公开估算公式。 | `test_missing_assists_stays_unknown_instead_of_fabricating_impact_or_rating`、独立数字断言 Impact=1.846、Rating=1.51 |
| 一份结算内重复身份、部分无效选手会覆盖完整统计 | 所有名单都先检查唯一身份与有效名字，不再只检查锁定十人；任何选手失败都整次拒绝。 | `test_duplicate_steam_identity_is_rejected_even_without_ten_player_lock`、`test_one_invalid_player_does_not_silently_replace_a_full_map_with_partial_stats` |
| 同一 result_id 换内容仍返回“重复成功” | 新结算绑定内容指纹；同编号但比分/地图/内容不同返回冲突。旧记录无指纹时核对基本比分、身份和可核实统计。 | `test_same_result_id_with_different_content_is_a_conflict_not_a_duplicate` |
| 并发重试可能多写一版统计 | 结算读状态前取得比赛写入锁；二次请求在第一次提交后识别 duplicate。 | `test_concurrent_retries_create_one_stat_version_only` |
| BO1 可向残留的第二图推送，重复图不指定槽位会猜第一图 | GSI/GOTV/导播都按 BO 和 has_map 有效槽位匹配；结算遇同名多个槽位必须明确指定。 | `test_map_slots_outside_bo_limit_are_rejected`、`test_disabled_bo_map_cannot_receive_live_frames`、`test_ambiguous_repeated_map_requires_an_explicit_slot` |
| 导播可谎报系列赛结束，或在 2:0 后再添一图 | series_complete 按确认胜场计算，非法结束声明与多余新图被拒绝；不自动把 matches.status 改 completed。 | `test_series_complete_claim_cannot_end_an_incomplete_bo3`、`test_actual_series_completion_is_derived_without_auto_finishing_the_match`、`test_an_extra_map_cannot_be_added_after_the_series_is_decided` |
| GOTV 中途 6:5 被算成已经赢下一图 | 中途帧只更新地图小分，内部标记 unconfirmed_map_slots；Demo/导播只确认自己的槽位，其他中途图不进入系列胜场。 | `test_mid_map_six_five_does_not_award_a_series_map_win`、`test_only_explicitly_confirmed_maps_count_after_multiple_relay_frames`；Demo 分工另有同链路回归 |
| GOTV 中途帧覆盖已确认 Demo | 原来无来源保护；现在中途推送不能覆盖该图已有 final 统计。 | `test_mid_map_relay_cannot_replace_already_confirmed_demo_stats` |
| GOTV 只核对 A 队名，任意 B 队也能落入本场 | 现在双方名称/简称和已知 Steam 身份共同检查；未知 A/B 字母不再被当作 B。 | `test_both_team_names_must_agree_before_replacing_gotv_stats`、`test_missing_identity_or_unknown_team_letter_cannot_be_silently_assigned` |
| 半场换边首帧把上一回合胜方记反 | 当前 CT/T 已换，而 previously.round 说的是上一回合；现在用前一帧身份解释刚结束的回合，当前记分板仍用新身份。 | `test_halftime_transition_uses_the_previous_sides_for_the_finished_round` 红测 t1/t2 记反，修后正确 |
| App 重发旧回合时历史胜方随新 CT/T 翻转 | 重发缺 winner 时重新用当前选边推算；现在优先保留同回合已有的固定队伍胜者。 | `test_old_app_round_events_do_not_flip_winner_when_resent_after_halftime` |
| 非法 GSI 嵌套结构、无穷计时或坐标造成 500/坏雷达 | 收数前检查对象和主要数值结构；计时、坐标和只读旧状态增加容错。 | `test_malformed_numeric_and_nested_shapes_are_rejected_before_database_work`、`test_nonfinite_radar_coordinates_are_not_returned`、`test_nonfinite_timer_is_unknown_instead_of_crashing` |
| 后半段保存失败可能留部分结果 | 直播三类写入由统一连接包装负责一次提交；错误返回也显式回退，不靠关闭连接碰巧回退。 | `test_a_late_failure_rolls_back_scores_stats_and_live_state_together` 验证比赛、统计、直播状态和账号记录不变 |

## 测试证据

- 第一批 21 项比赛/BP/对阵测试在原逻辑上出现 24 个断言失败（含子用例）；两个失败后的测试连接清理错误也在测试自身修正，没有当作产品问题。
- 直播第一批 37 项运行出现 30 个断言失败和 2 个错误；覆盖数值、缺值、身份、地图、重试、完成标记和计时。
- 对 BP 并发回归临时去掉新增写锁，确实复现“刚执行的 revision=1 被心跳覆盖成 revision=0”；恢复锁后通过。
- 4se、8se、4de、8de 均按真实队伍 ID 跑完每个节点，核对胜方与败方来源、重复刷新不多造比赛。
- 阶段性联合回归先后达到 79 项、154 项、156 项、158 项全绿；最终统一针对性复核为 **159 项全部通过，52.518 秒**。包含已有测试，不将它们误报为新增测试数量。
- 三份新测试文件共 67 个新增测试方法。直播测试复用了 21 个既有测试方法，因此运行数会大于新增方法数。
- 最后增加 HTML/API 共用即将进行列表一项，也已包含在上述 159 项最终结果中。

复核命令（在本隔离目录运行）：

```powershell
$env:PYTHON_DOTENV_DISABLED='1'
$env:TMP=Join-Path $PWD 'output/tmp-match'
$env:TEMP=$env:TMP
& 'E:\Code\Projects\80GOTV\.venv\Scripts\python.exe' -m unittest tests.test_refactor_match_integrity tests.test_refactor_bracket_integrity tests.test_refactor_live_integrity tests.test_live_ingest_security tests.test_live_data_stream tests.test_bp_manager tests.test_bracket_generation tests.test_match_lifecycle_workflow tests.test_admin_match_edit_locks tests.test_broadcast_api tests.test_broadcast_map_result tests.test_match_status -q
```

父目录虚拟环境未安装 pytest，因此采用同一解释器自带的 unittest，没有额外安装环境依赖。

## 旧测试的精确调整

- `test_admin_match_edit_locks.py` 的“开赛后缺省禁用字段仍可保存”用例，原夹具 BO3=1:0 却期待结束；经主分工授权，仅把该用例现场比分设为合法 2:0，原有保存字段断言完整保留。新增测试另行确保 BO3=1:0 不能结束。
- `test_broadcast_map_result.py` 仅将旧自定义 Impact 预期换为新公开估算入口，并加独立 1.846 数字断言，保留落库、比分、重试及身份的全部断言。
- 新估算不是 HLTV 官方保密公式。只影响新采集和用户明确重新导入的数据，没有批量改写真实历史 Rating。
- Demo 分工已在 `sync_match_scores` 中接入已结束比赛的积分重核；改分和积分一起保存或一起回退。其分工另有胜方改反后撤回旧积分、积分故障导致整次回退两项红绿测试。

## 保留的规则与剩余验证

- 结束比赛仍需管理员明确操作；没有因“先到 13 分”或客户端布尔值自动结束。没有擅自假定固定回合设置、自定义服务器或加时规则。
- 单败/双败沿用已有赛制节点，包括原本单场总决赛；没有擅加双败总决赛重置规则。
- 兼容临时比赛、空旧名单的权限回退、负数临时队编号的既有含义；新统计仍用明确 match_team_side，不把临时编号冒充真实队伍外键。
- BP 的网站选边和导播的固定 team1/team2 身份保留；半场变化不交换网站队伍身份。
- 未明确确认的 GOTV 统计保持 provisional；明确锁定十人后的正式结算才按原有规则标 final，不伪造缺少的十人数据。
- 没有连接 Turso 或公网检验事务行为。并发与回退证据来自本地真实 SQLite 临时库；远端适配仍需独立环境验证。
- 没有真实开游戏、操作导播软件、听看比赛来验收。浏览器截图由主分工统一执行；本报告不把 HTTP/自动测试通过写成视觉或现场验收。
- 未对未知历史回合凭当前 CT/T 编造固定队伍归属；已有回合胜者会保留，真实上游仍应发送明确 winner。
