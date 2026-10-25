# 统计、Demo 与历史归属审查

日期：2026-10-26。工作位置仅为 `backend_refactor_20261026` 隔离副本。

## 范围与边界

- 已审查并修改：`utils/stats_calc.py`、`utils/demo_parser.py`、`services/performance_service.py`、`services/demo_service.py`、`services/player_service.py`、`services/award_service.py`。
- 补审后另修改：`utils/award_poster.py`、`utils/poster.py`；新增 `utils/stats_display.py`，只修缺失值和历史归属显示，不改原海报布局、尺寸、字体。
- 已审查并修改统计读取部分：`routes/stats.py`、`routes/players.py`、`routes/events.py`。未改页面布局或报名业务。
- 已通读：`services/player_awards_service.py`。其读取已发布奖项的规则没有发现本轮需要修改的确定性问题，原有奖项页面测试保留。
- 原版保存在 `backups/source-baseline-bca519e.zip`。本轮没有改父目录源码、提交、推送、部署或写入真实业务数据库。
- 两份真实 Demo 仅作为只读输入。其解析结果全部写入本隔离目录的 `output/demo-review-real/`。没有自动重算任何已保存的历史原始统计。

## 官方定义与估算

1. [HLTV 的 Rating 2.0 原说明](https://www.hltv.org/news/20695/introducing-rating-20)说明它包含击杀、生存、KAST、Impact、伤害等分项，并分 T/CT 侧处理。Impact 使用多杀、首杀、残局等信息；该页面没有公开可完全复现的精确公式。
2. [HLTV 的 Rating 2.1 说明](https://www.hltv.org/news/40051/introducing-rating-21)再次明确完整公式保密，也解释了 Impact 使用回合内击杀、助攻、死亡、首杀与残局等因素。不能把只有 KPR/APR 的线性近似称为官方公式。
3. [原回归作者 Dave 的文章](https://dave.xn--tckwe/posts/reverse-engineering-hltv-rating/)给出公开近似；[CS Demo Analyzer 官方 player.go](https://github.com/akiver/cs-demo-analyzer/blob/main/pkg/api/player.go)沿用它。本轮采用 `Impact ≈ 2.13*KPR + 0.42*APR - 0.41`；Rating 近似的常数项为 `0.1587`，不是原站内的 `0.2698`。方法名为 `csda_hltv2_regression_v1`，明确记录 `official_hltv_formula=false`。
4. [HLTV 的 Rating 3.0 说明](https://www.hltv.org/news/42485/introducing-rating-30)已不再使用旧 Impact 分项。本站约定仍是 Rating 2.0，本轮没有擅自升级到 2.1 或 3.0。
5. [WPA 原始论文](https://arxiv.org/abs/2011.01324)使用动作前后的获胜概率变化评价贡献；[作者的 Awpy 项目](https://github.com/pnxenopoulos/awpy)提供数据解析工具。这不是把首杀和残局计数相加就能得到的东西。本轮没有虚构 WPA 或称本站 `rws_basic` 为这类概率评分。

以上网页和源码均已在本轮实际联网读取，不是仅凭记忆填写的来源。

## 已复现并修复

| 问题与触发条件 | 原因与影响 | 修复与失败测试证据 |
| --- | --- | --- |
| Demo 的 Rating 与展示的 Impact 不是同一口径 | CSDA 用回归近似算 Rating，本站另用首杀/多杀/残局自定义权重算 Impact。同一场数据的两个指标无法对应。 | 新增明确命名的 `estimate_hltv2_impact`；新 Demo 与新直播共用它。旧 `calculate_impact` 仅为旧调用保留并标为自定义。修前示例 Impact 为 0，CSDA 同输入应为 1.82。 |
| Rating 近似常数写错，且无回合输入可能除零 | 原常数为 0.2698；先判断整型 0，再把 None、负数或字符串转成 0 后继续相除。 | 按原作者和 CSDA 修为 0.1587；先规范回合数再判断。删除没有来源的 3 分上限；必要指标缺失时不猜 Rating。修前示例 1.60，源公式 1.49；None/-1/字符串0均出现除零。 |
| 短图和长图被同等对待 | 部分赛事、对比、选手最近比赛和趋势图仍用 `AVG` 平均每图均值。 | 复用 `weighted_average_sql`：Rating/ADR/KAST/Impact 按有记录的回合，爆头率按有记录的击杀数。10回合0.8与30回合1.4，原页面为1.10，修后1.25。 |
| 未知指标进入平均数分母 | Python 聚合把 NULL 当0，给零回合行分子额外权重；部分比例把缺分子当0。 | Python 与 SQL 共用相同有效记录规则；修前示例 Rating 1.32，应为1.25；已知10杀10回合加未知30回合，原比率0.25，应为1.0。 |
| 已记录的0分在趋势图中消失 | 以真假值判断是否有数据，0与None被混为一谈。 | 明确判断 `is not None`。修前图表 `[null]`，修后 `[0]`。 |
| 汇总表把完全未知指标显示为真实0 | 旧汇总表所有均值列均为 NOT NULL，内部必须保留兼容占位值。 | 不重建表；新增 `summary_metric_sql`，公开排行读取时依据当前原始行的可用性返回None。真实0仍显示0。内部缓存约束与对外可用性是两层，不能混淆。 |
| 导入缺字段直接存0 | `insert_match_stat` 对所有缺字段均使用 `.get(..., 0)`。 | 未提供的可选字段存NULL，显式0保留；原有 `flash_count_recorded` 同步记录真正已知的闪光次数。 |
| 旧队伍归属被今天的队伍覆盖 | Demo 映射先使用选手当前队伍，而且只看 A 队；历史转会或只有 B 队能识别时会反转或拒绝。 | 优先比赛保存的固定名单；A/B共同核对，再看队名，最后看当前队伍。矛盾信息拒绝，而不是随便取第一条。保留临时队伍 `match_team_side` 的兼容方式。 |
| 同名或重复身份误归属 | 昵称匹配返回第一个同名人；重复Steam或多个输入对应同一网站选手，在替换旧版本后才触发唯一约束。 | 只允许唯一且没有Steam冲突的兜底身份；写入前检查重复Steam、重复网站身份、缺失队伍。修前重复身份触发数据库异常，修后提前中文拒绝且旧结果未被改动。 |
| 重算辅助函数改写旧版本 | `backfill_demo_performance` 的清零和更新没有排除 superseded。 | 所有更新仅作用于当前有效版本。反例中旧1v5=7被改为0，修后旧7、残局总数7、RWS8均保留。没有实际调用该函数改真实历史。 |
| 合并选手复活旧结果并丢版本 | 将源档案全部行逐条按击杀多少覆盖目标第一行，包含已失效历史，且遗漏来源/版本/固定左右队等字段。 | 只在当前行中挑保留结果，优先最终结果、较新版本、完整记录；其他行仅改为superseded，全部原始统计转到保留档案，不删除统计行。修前旧40杀覆盖新10杀，修后保留新10杀/版本3和全部3行历史。 |
| 合并选手丢年度排名 | 删除源选手时，年度排名通过数据库关联被自动删除。 | 无冲突的年度排名转给保留档案；同一年双方已有排名则在任何修改前拒绝，要求先确认，不擅自删或选一条。反例修前排名列表变空，修后原第一名保留。 |
| 赛事与奖项图使用今天的队伍 | 对历史统计连接 `players.team_id`，转会后旧赛事挂到新队。 | 赛事和奖项从该赛事实际 `match_stats.team_id` 取正式队；多队或未知不猜。临时队仍保留在原始数据，不强塞进正式队表。 |
| 奖项平均数被缺失地图拉低 | 乘数中NULL被跳过，但分母把这些地图回合全加上。 | 复用按指标有效性的加权函数。反例已知Impact1.2加另一张未知图，原结果0.3，修后1.2。 |
| 分边数据缺失却造出评分 | 缺少伤害事件时按0伤害算ADR；用整图KAST替代分边KAST；没有该侧回合仍造一回合。 | 新 Demo 从完整事件算分边击杀/助攻/KAST，并核对汇总一致性；缺伤害或事件不完整时分边值为None；没有该侧回合不造评分。缺整图回合不再造出1回合。 |
| 缺失闪光事件被记录为0 | `flashbangsExplode=null` 被当作空数组；只知道投掷时也造出致盲时间和助攻0。 | null保持未知，空数组才代表明确0；致盲和助攻分开按各自事件的可用性保存，未知不会覆盖已有值。 |
| 解析成功误读别的旧JSON | 进程返回0却没有新输出时，任取输出文件夹第一个JSON。 | 每次创建唯一空输出目录，仅接受本次目录中的确定结果；没有输出或有多个不明结果则失败。真实验证发现本机旧csda只接受目录，因此没有强行依赖新版才支持的输出文件参数。 |
| 缺失比分覆盖已保存比分 | 缺字段默认0，可能把13:7变成0:0。 | 未知、非法或负比分不更新已有结果。正常比分仍通过共享 `calculate_map_wins` 按BO范围重算，避免高地图槽残留计入。 |
| 一张最终Demo把其他未结束地图算成胜场 | 另一张图的GOTV中途11:10也被总分函数视为已赢一图。 | 与直播审查共用 `update_unconfirmed_map_slots`：Demo只确认自己的槽位，其他未确认图不计胜场，原直播JSON其他字段保留。反例原总分2:0，修后1:0。 |
| 半场比分混入加时和未知回合 | 一次换边后所有后续回合都计入下半场；未知winner=0与未知side=0比较也被当成获胜。 | 常规半场只计有效阵营与赢家，并排除 `overtimeNumber>0`；完整加时事件仍留在原始扩展数据。反例下半场原3，修后1。 |
| Demo更正已结束比赛后预测积分仍沿用旧赛果 | 总比分变了，但积分以前依赖有人打开预测页时才更新，不能保证与导入同成败。 | `sync_match_scores` 对已结束比赛同事务重核本场积分，无内部提交。反例原8分错误保留，修后撤为0；积分步骤故障时地图分、总分、积分全部回退。 |

新增反例位于 `tests/test_refactor_stats_consistency.py` 和 `tests/test_refactor_demo_history.py`。每个表中确定性问题均先运行暴露错误的测试再修复；合并后重新初始化的联合测试另与主审者的数据库反例配合。

## Demo 扩展能力

当前仍使用已接入的 CS Demo Analyzer，不为获取现有解析器已经提供的数据而额外引入第二套运行依赖。

- 新解析的扩展数据保留回合、原始击杀/残局、伤害、选手经济、购买、下包/拆包/爆炸、闪光/致盲、手雷爆炸、烟雾展开事件。未提供的事件为None，明确空数组为已知无事件。
- HE和烟雾计数来自真实事件；分别是爆炸次数和展开次数，不把它们冒充所有可能的投掷动作。缺少合适事件的燃烧弹次数不造0。
- 分边回合、助攻、KAST与完整性标记保存在扩展选手数据中，供后续统计入库设计使用。
- `analysis.schema_version=2`，保留方法来源、方法名、原Demo校验标识、事件可用性。解析器版本无法从现有数据确认时明确为None，不捏造版本。
- 新预览追加写入 `static/demos/analysis/<唯一ID>.json`；始终以独占新建方式保存，不覆盖原Demo或旧解析文件。文件内状态为preview。导入成功的引用和统计版本随现有 `matches.map_halves` JSON 保存；失败导入最多留下未被数据库标记为成功的预览文件。
- 新文件位于原本完整备份覆盖的Demo目录；主审者已统一屏蔽这棵目录的直接静态访问。Demo下载仍只从比赛配置的单个根目录文件名读取，不能用该接口取analysis子目录。

已实际读取 [CSDA 官方导出说明](https://github.com/akiver/cs-demo-analyzer/blob/main/README.md)、[官方事件模型](https://github.com/akiver/cs-demo-analyzer/blob/main/pkg/api/match.go)、[HE事件](https://github.com/akiver/cs-demo-analyzer/blob/main/pkg/api/he_grenade_explode.go)、[烟雾事件](https://github.com/akiver/cs-demo-analyzer/blob/main/pkg/api/smoke_start.go)和[经济字段](https://github.com/akiver/cs-demo-analyzer/blob/main/pkg/api/player_economy.go)。

也实际读取了 [demoparser2 官方项目和使用说明](https://github.com/LaihoE/demoparser)。它能查询击杀等事件、逐时刻属性、经济、装备、存活和位置；适合后续需要的更细状态。切换解析器仍需统一回合范围和数据完整性验证，本轮没有声称已用demoparser2解析真实Demo，也没有新增未经验证的概率模型。

## 验证记录

- 第一批17项反例修前为15项失败、4个错误（含子测试）；随后全部通过。
- 第二批真实失真反例包含旧40杀覆盖新10杀、年度排名被删除、旧JSON误用、缺比分清零、半场加时混入、闪光NULL伪0，均保留对应失败证据和回归测试。
- 两图真实解析：Mirage17回合、10人、闪光108、HE52、烟雾67；Inferno22回合、10人、闪光86、HE59、烟雾74。逐人Impact与CSDA同输入近似一致；重新计算Rating与CSDA导出四舍五入到两位后的值也全部一致，20条记录差异0。
- 真实解析并不代表所有衍生项都完整。两图击杀/死亡事件与摘要可完整对应的分边记录分别只有7人和3人，其余维持未知，不假称全员分边精确。
- 将这两图导入单独临时数据库：10人、39回合，生涯汇总与赛事筛选的Rating/Impact对期望回合权重差异0。重导第二图后有效20行、旧历史10行、版本2，旧行除失效状态外所有原始指标不变。
- 证据文件：`output/demo-review-real/comparison-summary.json`、`rating-formula-summary.json`、`import-comparison-summary.json`；每图保留原解析JSON和扩展 `performance-v2.json`。
- Python测试使用父目录现有 `.venv/Scripts/python.exe`，禁用dotenv，TMP/TEMP全部设为隔离目录 `output/tmp-stats`。该环境没有pytest，因此采用项目现有unittest，不安装依赖。
- 首轮新增36项回归，加上原有52项相关测试，共88项通过。对本子任务负责的Python文件执行Ruff检查通过；本轮没有把主审者负责的全项目测试数冒充自己的覆盖。

## 海报补审

主审者将报告中原先保留的海报显示问题交回本子任务后，另补12项海报反例及2项Demo积分联动反例。首次海报测试为7项失败、4个错误，真实0保留的测试原本就通过；修复后全部通过。以上新增测试与原相关测试最终合计102项通过。

| 显示问题 | 修复结果 |
| --- | --- |
| 奖项服务末尾把全部None改成0 | 保留原None；KPR/DPR、多杀比例和击杀差只使用对应指标已记录的回合，未知不被零掩盖。 |
| 图中未知比分、K-D和Rating变成0或0:0 | 未知显示 `-`，真实0仍按原格式显示；NaN、Inf、非法数值也视为未知，不输出nan/inf或导致绘图失败。 |
| 缺少DPR时反而得到满值雷达轴 | 缺失轴没有数据点；部分数据时不跨越未知轴填出完整面积，全缺失时只保留原网格和标签。真实零值点不再被抬到8%的虚假最低值。 |
| 未知所属队伍走else被当成队2 | 共用 `resolve_match_team_side`：显式 `match_team_side` 优先，其次历史team_id，兼容旧 -1/-2；未知或两侧相同ID时不猜。奖项抬头也使用该场历史侧别，不使用今天的队伍。 |
| `de_mirage` 与 `Mirage` 无法匹配，生成0分 | 用原有 `match_map_slot` 规范匹配地图并遵循BO上限和有效地图槽；找不到的地图或未知侧别返回None，不生成0分。 |

新增公用工具实际接口：

- `optional_number(value)`：返回有限浮点数或None；保留0，拒绝布尔值、NaN、Inf和非法字符串。
- `format_stat(value, digits=0, *, suffix='', signed=False, missing='-')`：统一显示已知数值和缺失标记。
- `resolve_match_team_side(stat, match)`：返回 `t1`、`t2` 或None，不查看当前阵容。

两张图使用隔离临时库和测试选手生成，已实际打开检查，原1600×900布局及字体不变，未覆盖任何原图：

- 完整值：`output/ui-audit/posters-complete-values.png`。
- 缺失值：`output/ui-audit/posters-missing-values.png`。

完整图显示比分和雷达数据；缺失图显示缺失标记 `-`，没有伪造的零分或雷达面积。该视觉检查只证明本地测试图的绘制结果，不代表对真实选手历史数据的人工内容验收。

比赛海报入口的适配要求已交主审者和比赛负责人：`routes/match_assets.py` 必须把原始None比分及唯一的有效 `match_team_side` 传给工具，不能先用 `or 0` 抹去缺失信息，也不能遗漏现代临时队伍的显式侧别。最终入口验收还需覆盖该调用链，不能只以直接调用绘图函数代替。

## 公开排行计数补审

独立复查发现计数也存在同类问题：原始击杀、死亡、回合等全NULL时，汇总表因旧NOT NULL约束保存0；无筛选排行直接读取这些缓存，而筛选排行用 `SUM(COALESCE(..., 0))`，两条路径都把未知显示成真实0。

- 只修改 `routes/stats.py` 的公开排行、总览必要读取及 `templates/stats.html`、`templates/stats_detail.html` 的显示文字，没有修改布局或CSS，也没有改主审者负责的 `front_api`、`public_data_service`。
- 无筛选排行对击杀、死亡、回合、残局、首杀、首死使用现有 `summary_metric_sql` 检查当前原始数据是否真的记录。未记录返回None，真实0仍为0，旧失效版本不会让当前未知值变成可用。
- 筛选和分边计数使用保留NULL的SUM。击杀差、K/D、首杀成功比例任一必要输入未知时保持未知，不把另一个输入当0；没有意义的0除0也不造数。
- 无筛选的排序按相同的有效输出alias执行，未知值排到最后，不再让缓存占位0排在已知负数之前。原有回合权重不变；T/CT历史评分与ADR的 `NULLIF(...,0)` 兼容规则保留，没有把历史占位0猜成实测0。
- 模板显示未知为 `-`，保留真实0、真实 `+0` 和已记录0击杀且有死亡时的 `K/D=0.00`；未知差值不会再触发模板比较错误。预测页刚接入的两个只读helper保持不动。
- 新增 `tests/test_refactor_missing_counts.py` 10项。首批9项修前出现12个失败（含子测试），随后通过；另补已知负数与未知缓存0的排序用例。本次与相关既有测试定向合计51项通过，Ruff检查通过。

使用独立临时数据库与独立浏览器会话，实际检查选手排行、K/D排行的1440px桌面和390px手机截图。未知行显示 `-`，零值行保留0，桌面没有文字重叠；手机沿用原表格内部横向滚动，页面宽度未溢出（`scrollWidth=clientWidth=390`），浏览器控制台错误0。该临时服务和本轮浏览器会话检查后均已关闭，未影响主审者使用的服务或真实数据。

- `output/ui-audit/missing-counts-players-desktop.png`
- `output/ui-audit/missing-counts-players-mobile.png`
- `output/ui-audit/missing-counts-kd-desktop.png`
- `output/ui-audit/missing-counts-kd-mobile.png`

## 尚未统一的历史与能力限制

- 旧Impact可能仍是本站自定义值，新值为CSDA回归近似。没有自动重算旧原始行，因而不能声称整个历史已统一公式；全时段平均可能仍包含旧口径。旧行缺少算法标记，不能仅凭数值猜出处。以后需在用户确认后从原Demo重导或明确区分数据方法。
- 数据库尚无T/CT回合数、分边KAST/助攻列；扩展文件已保存新计算结果，但旧分边汇总仍只能保留原有有限平均方式，无法冒充精确回合加权。修复这层需要另行设计持久化字段或缓存，不能每个访客请求现解析Demo。
- 旧分边字段曾以0作缺失占位，部分兼容读取仍使用NULLIF0。没有来源标记时无法可靠区分每个历史0是未记录还是真实0。本轮没有猜测并批量改写。
- 奖项和比赛海报的None格式化问题已在补审中修复，并通过本地图片与绘制文本检查。没有改变图片布局；真实历史原始数据缺失本身并没有被“补出”。
- 临时队伍没有正式team表记录，奖项图无法总是还原历史队名时保持空值，不把当前正式队伍强加给过去的临时队。
- 多杀与残局保留现有事件重建规则；无完整逐回合名单时，残局是否完全可靠仍应结合真实回放人工复核，不能以测试通过替代比赛内容验收。
- 本子任务没有调整页面布局；最后的真实页面截图、全项目回归和整体验收由主审者统一完成。没有公网操作。
