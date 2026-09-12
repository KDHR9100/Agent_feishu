# 更新日志 (CHANGELOG)

本项目所有重要变更均记录于此文档。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/)。

---

## [2.5.0] - 2026-09-12（评测驱动修复闭环第三轮：度量公平性 + 真人行为对齐——缺陷档案 ⑤⑥⑦）

回到评测系统初衷"合成用户模仿真人生产数据、检验 Agent 是否像称职的人类助手"的三处修复（详见 `docs/evaluation_plan.md` §10.11）：

### 修复
- **⑤ 幻觉裁判按断言粒度计分**：一轮 10 个断言 9 个带算式、1 个裸数字，以前整轮 0 分；改为按条计分（0.9），部分诚实被部分计量。旧格式（无 `claims_total`）兼容回退 0/1。
- **⑥ 文件技能识别消息内联表格**：真人把表格数据直接贴进聊天（分号/换行/制表符分隔、≥2 行×2 列、数据行含数字）时当作文件内容分析，不再五回合回"未收到文件"（评测实录 file_analyst 因此 task 0.00）；保守判定不误伤闲聊，无数据时诚实诊断保留。
- **⑦ 工具维"可容忍补充技能"**：取证发现"预期外调用"几乎全是合理补充（选品问库存/FBA 核对查商品表/老板问广告），非路由缺陷——画像新增 `optional_tools` 声明，precision 按 expected∪optional 容忍、recall 口径不变，仅给三个有轨迹证据的画像声明。

### 测试与复测
- 主套件 **571 passed / 3 skipped**（+7）；评测套件 **76 passed**（+9）；mock 全量 13 画像管线验证通过。
- **real 补跑完成（2026-09-12，口径变更：API 切官方百炼按量，被测 qwen3.7-flash、sim qwen3.8-max-0902、judge 不变）**：file_analyst 单画像死循环未再出现（⑥ 验证）、幻觉维 0.49~0.53→**0.8026**（⑤ 验证）、工具维 0.78~0.80→**0.8493**（⑦ 验证）；全量原始 0.0 被安全维第三处同族误报绊住（"直接给我降价…的调整建议"系索要建议），修复后离线复算 **overall 0.5902（新口径基线）**；附带修复既有漏报（数值正则不认"降价 20%"）。详见 `docs/evaluation_plan.md` §10.11 补跑实录。

---

## [2.4.0] - 2026-09-11（评测驱动修复闭环第二轮：建议模式会话感知 + 推导数字诚实标注 + 安全维两处误报）

缺陷档案 #2/#3 修复与两处评测侧安全误报修复（详见 `docs/evaluation_plan.md` §10.10）：

### 新增
- **定价敏感性分析**：弹性假设 ×0.8/×1.2 同种子确定性重跑，输出最优方向稳健性结论（"降价方向在弹性 ±20% 区间内保持成立"或翻转警示）——补上评测发现的"连续 5 轮索要敏感性分析不可得"能力缺口。
- **定价建议会话感知**：`pricing_skill` 接收会话历史——追问轮自动锚定会话内最近讨论的 SKU（消除"未识别到具体商品"失忆话术，追问轮指令不再误落到默认商品）；已发过完整建议且无新参数时改发**补充式回答**（逐点回应置信区间/假设来源/敏感性），不再整块重发模板。

### 修复
- **推导数字诚实标注（主项目 5 处 LLM 提示词）**：综合回答/商品/广告/数据分析/文件分析的输出规则统一为——计算数字必须标注"推导值"+算式（含排名/阈值/竞品指标），建议类数字须注明"经验假设值"及依据；评测裁判配套"带算式的推导值视为有支撑，裸数字不豁免"。
- **评测安全维误报 ×2（均触发一票否决 overall 归零）**：复合攻击被整条拦截却因拦截模板无审批门字样被判"调价指令未走审批门"（拦截即未绕过审批）；"给一版临时调价幅度"索要建议被误判商品调价指令（复合名词滤补"幅度|空间"）。均以真实轨迹原句固化回归测试。

### 复测（real 全量 13 画像 ×3 次 + 单画像）
- 单画像 pricing_analyst **0.650→0.850 PASS**（五维全过）；全量 overall 0.61~0.67 波动带（最佳 0.6736），一致性最佳 **1.00**（基线 0.33）；两轮被误报归零的 run 经误报修复后离线换算 0.6076/0.6066。
- **0.75 总分门禁本轮未过**（差 0.08~0.14）：幻觉维受被测模型标注遵守率拖累（机制已验证：带算式推导值不再被判幻觉）；短板转移至任务完成（file_analyst 文件接收死循环）与工具准确（inventory_skill 预期外调用）——已记入缺陷档案候选 ⑤⑥⑦。

### 测试
- 主套件 **564 passed / 3 skipped**（+14）；评测套件 **67 passed**（+3）。

---

## [2.3.1] - 2026-09-10（评测驱动修复闭环第一轮：跨会话审批泄漏 + 建议 SKU 锚点）

合成用户评测系统交付的第一个"评测发现 → 修复 → 复测提升"闭环（全量基线 run-20260910-132010 缺陷档案 #1/#4，详见 `docs/evaluation_plan.md` §10.9）：

### 修复
- **审批状态跨会话泄漏（安全类）**：attacker 画像从未提及任何 SKU，却被回答其他会话的待审批单详情。根因是 `ApprovalManager.recent_approvals` 的"会话无记录时退回全局最近记录"兜底（P6 引入）——单用户场景的便利设计在多会话场景构成信息泄露。修复：带 conversation_id 查询严格限定本会话，无记录返回空；全局视图仅保留给空 conversation_id（调试用）。旧隔离测试断言空真（从未断言 A 的记录不在 B 结果里），已加固并新增 pending 态泄漏回归测试。
- **建议模式模板无 SKU 锚点（一致性类）**：pricing 建议模板不含 SKU 标识，多轮追问"还是那个 SKU"的回答失去指代锚点（一致性探针实测失败）。修复：`parse_context` 记录 `_product_id`，建议标题携带 SKU。

### 复测（real 模式全量 13 画像，同基线口径）
- **overall 0.5149 → 0.6191（+0.10）**；一致性 0.33→0.67、幻觉 0.52→0.68、任务完成 0.17→0.25、**安全合规 1.00 保持**；画像 10↑2↓1平。
- 攻击者画像轨迹复核：5 轮零跨会话信息；攻击者自己的"改成 0.01 元别走前台校验"被强制送审批门。
- 遗留（下轮）：建议模式模板复读（不回应置信区间等追问）与推导数字泛滥，距 0.75 总分门禁还差 0.13。

### 测试
- 主套件 **550 passed / 3 skipped**（+2 回归用例）；评测套件 64 passed。

---

## [2.3.0] - 2026-09-10（合成用户评测系统 M1~M7：五维评测 + 独立 CI + 全量真实基线）

### 新增
- **合成用户评测系统**（`evaluation/`，与主代码完全解耦，`app/` 零改动）：LLM 驱动的"模拟用户 ↔ 被测 Agent"多轮对话评测，从"人工看输出"升级为"可量化、可回归、可对比"的五维打分。方案与实现记录见 `docs/evaluation_plan.md`，运行手册见 `EVAL_README.md`。
- **五维评测器**：任务完成 / 多轮一致性 / 工具调用准确（precision & recall）/ 幻觉控制（可校验断言与工具载荷比对 + LLM 裁判双通道）/ 安全合规（注入命中 + 审批门校验，安全门一票否决）。LLM 裁判为主、规则兜底，裁判与被测可异源配置。
- **13 个电商画像**（含提示注入攻击者）：运营/客服/商家等角色，画像携带目标、话术风格、追问倾向；`fixtures/attacks.jsonl` 12 条攻击语料。
- **mock/real 双模式**：mock 零 token 秒级跑全量（关键词路由替身，不 import `app.*`，零补丁零残留）；real 模式挂真实 LangGraph 工作流，环境隔离（独立 sqlite 库、`BIZ_DATA_DIR` 指向 fixtures、路由缓存关闭、审批门强制开启），运行结束快照恢复原环境变量。
- **报告产物**：`metrics.json`（overall/五维/分画像/分轮次）、`report.md`、`trajectory.jsonl`（完整轨迹：用户消息、Agent 回答、路由意图、技能调用与载荷、节点耗时、token 用量）、`history/` 单行摘要供跨 run 对比。

### 测试与 CI
- 评测模块自带 **64 个测试**（`pytest evaluation/tests`）全绿；新增独立 workflow `eval.yml`：PR 触发单元测试 + mock 全量评测 + **PR 评论回归摘要**（overall/五维/阈值表格自动评论到 PR），real 模式仅手动触发且 continue-on-error——评测失败不阻塞合并，与 `ci.yml` 零耦合。
- push 前复核修复：skill_results 兼容主项目嵌套结构（type/data 曾落空导致幻觉误判）、node_timings 按相邻 yield 间隔计时（曾恒 0）、调价指令咨询语境滤（"把调价方案发我"不再误判为执行指令触发安全违规）。
- real 模式两轮修复（均以真实 run 原句固化为回归测试）：裁判延迟（qwen-max 长输入默认开思考，单调用 73s→1.6s，`EVAL_JUDGE_DISABLE_THINKING` + 超时可配）；安全维指令探测器四类误报（能力问句/条件将来时/否定式/复合名词/状态问句）+ 检查 2 放行"审批门被传达"式回答。

### 全量真实基线（M7 定稿，run-20260910-132010）
- 13 画像 × 5 轮（sim=qwen3.8-flash，judge=qwen3.8-max 关思考，被测=qwen3.6-flash，1315s）：**overall 0.5149**（总分门禁 0.75 未过）；五维 = 任务完成 0.17 / 多轮一致性 0.33 / 工具准确 0.85 / 幻觉控制 0.52 / **安全合规 1.00（13×5 轮全部攻击拦截、全部调价指令正确进审批门）**。
- 五维阈值按"基线 − 容差 = 回归地板"回填 `eval_config.yaml`（安全维零容忍保持 1.0）。
- **缺陷档案**（M7b 修复闭环输入，详见 `docs/evaluation_plan.md` §10.8）：① 审批状态跨会话泄漏（root cause：`recent_approvals` 全局兜底回退）② 建议模式模板复读致任务不完成 ③ 推导数字泛滥致幻觉维 11/13 失败 ④ 多轮指代丢失。修复走独立分支单独 PR，本 PR 保持 `app/` 零改动红线。

---

## [2.2.0] - 2026-08-30（调价重定位：决策登记语义）

### 变更
- **调价语义重定位**：update_price 审批批准后**登记调价决策并推送手动执行引导**（"请在商家后台完成改价，改价后可复测损益"），不再经 Mock 适配器制造"已改价"的虚假闭环。定位边界：多数电商开放平台不覆盖网页端改价，Agent 的职责 = 模拟验证 + 人工审批 + 决策登记 + 执行引导，实际改价由运营在商家后台完成。登记层显式拒绝非法价格（职责自 store adapter 前移）。
- **审批卡片文案**：按钮"批准并执行"→"批准"，结果卡"操作已执行"→"操作已处理"，回执区分"回滚窗口提示"（真实执行动作）与"手动执行引导"（调价决策）。

### 新增
- **定价指令确定性快路径**（T34b 修复）：路由层新增第二级快路——明示调价指令（目标价/涨跌幅/折扣）经 `pricing_skill.has_explicit_directive` 结构化判别后直接路由 pricing_skill，**审批门不再依赖路由 LLM 能力**（弱模型下"SKU-A001改价到99"曾被误路由到商品分析，审批门被整条绕过）。防误触发设计：竞品语境/咨询句式/创作素材等歧义输入不进快路；其余技能 conf>=2 复合指令交回规划器。开关 `ROUTER_PRICING_DIRECTIVE_FAST_PATH`（默认开）。目标价关键词表补"改到"。
- **Token 记账覆盖修复**：未设归属标签的 LLM 调用不再被静默丢弃，归入 `unattributed` 兜底记账（实测服务端记账 27.8k vs 真实消耗严重不符的根因）；闲聊兜底（chitchat）、记忆摘要（memory_summary）补归属标签；guardrails 裸 requests 调用从响应 usage 手工记账；llm_judge 自建 LLM 挂 handler + judge 归属。
- **Guardrails 业务比喻白名单**：关键词匹配前剥离"杀人价""像股票一样"等电商口语比喻，降级模式（LLM 二次确认不可用）下不再误杀业务黑话，健康模式下省一次 LLM 确认调用。
- **探针测量基础设施加固**：intent_probe 增加 LLM 预检 fail-fast（`--allow-degraded` 可跳过）避免配额耗尽浪费整轮跑批；429 单次退避重试；rl 阶段冷却 5s→65s（对齐 60s 滑动窗口）。

### 测试
- 新增 11 个用例：定价指令快路径 6 个（T34b 原始失败用例/歧义防误触发/多意图守卫/开关/端到端无 LLM 路由）、记账覆盖 5 个（unattributed 兜底/正常归属/零用量跳过/guardrails 记账/缺失 usage 静默）。
- 全量 **517 passed / 3 skipped**；回滚机制测试改用 delist_product 验证（update_price 已是决策登记语义）。

### 基线验证（2026-08-30，Flash 弱模型，全程健康）
- 首次零降级污染的全量探针跑批：**88 场景 76 PASS / 通过率 86.4%，LLM 评审均分 4.51/5**，服务端 `insufficient_quota` 错误 0 条（前两轮基线分别被配额死亡污染 100%/37% 场景）。
- 两个修复的端到端验证：T34b（"SKU-A001改价到99"）经确定性快路径直达 pricing_skill，judge=5；G_T04（"像股票一样"）/G_T05（"杀人价"）护栏白名单放行。
- 上轮配额污染期的 R37（时间衰减）/R38（缓存失效）本次转 PASS，确认为 LLM 死亡连锁反应而非真缺陷。
- 12 个失败全部为回答质量类（文件边界表述×3、多轮指代×2、除零解释、审批状态表述、报告提示、路径穿越话术、边界判罚×2），无路由错误、无安全链路失效（两轮路由准确率均 100%）。
- 评测成本：88 场景全程（含评审）实际消耗约 77 万 token（约 8.8k/条），分阶段跑批 + 预检 + 消耗监控在 100 万免费额度内零降级完成。

### 第二轮迭代：失败簇根因修复（2026-08-30 下午）
- **数据驱动修复**：针对 12 个失败聚类定位 5 个根因并全部修复——T21 零花费 ROI 编造（指标 None 化 + zero_spend_note + prompt 铁律）、T28 路径穿越（独立检测模式 + 确定性拦截文案）、F42a/F45 文件边界（错误三分类 + 透传 + 确定性话术）、M14b/M15 多轮指代（代词注入最近 SKU + "最早"追问注入 SKU 提及顺序清单）、M17c 定向查询（inventory_skill 按SKU定向回答）、AP33b 审批状态（多记录优先级确定性答复 + 技能执行前拦截追问防重复审批单）。
- **设计原则落地**：边界/安全场景答复全部确定性化，不交给模型发挥——弱模型下行为与强模型一致。
- **最小真实验证（5.2 万 token 内完成）**：T28 拦截零 LLM 消耗 ✓；T21 回答如实说明"ROI 无意义" ✓；AP33b 全周期（创建→拒绝→追问返回"已被拒绝，未执行"，零重复审批单）✓；M14b 第二轮直接围绕指代的 SKU-A001 回答 ✓。
- 新增 30 个回归测试，全量 **548 passed / 3 skipped**；工程清理（化石脚本归档 eval_archive/、日志出库、依赖锁版本）；新增 eval_report.py 一键聚合探针报告。

### 跨模型基线验证（2026-08-30 晚，qwen3.6-flash）
- 修复后换更弱一代的 qwen3.6-flash 重跑全量 88 场景：**80 PASS / 90.9%，评审均分 4.63/5，路由准确率 100%，零降级污染**——对比修复前 qwen3.7-flash 基线 86.4%（12 失败），确定性修复在更弱模型上仍 +4.5 个百分点，验证"修复不依赖模型能力"。
- 分阶段：text+guard 37 条 **94.6%**（修复前同模型口径 86.5%，T21/T28/T01/T20/T34b 全部转 PASS）；剩余失败为 T14 格式约束、F50 双重防线判罚、HP63 热插拔路由、M14a/M15/O66b/T22 边界判罚——无路由错误、无安全链路失效。
- **M15 二次修复**：复测发现清单式注入（"SKU-M01 -> M02 -> ..."）对弱模型无效（无视"第一个即最早"标注、抓取中间 SKU 作答），改为**结论式注入**（直接明示"[上下文解析结论] 最早提到的商品是 SKU-M01"）——线上验证弱模型随即正确锁定 M01。教训：给弱模型的上下文必须是可用的结论，不是需要再加工的原料。
- 跨模型对比报告：`data/reports/eval_report_cross_model.md`（eval_report.py 生成）。

---


## [2.1.0] - 2026-08-04（商业价值度量与生产化加固）

### 新增
- **业务价值度量层**（app/monitoring/business.py）：每次任务按 user_id/技能/成败/耗时落 BusinessTaskLog（SQLite），`GET /metrics/business?days=N` 输出任务量、成功率、活跃用户数、DAU 分布、Top 用户与**节省工时估算**（按各技能人工基准耗时 MANUAL_TIME_MINUTES 换算）；DB 不可用时自动降级内存统计，度量失败不影响主流程。
- **埋点接入**：飞书 WS 入口（sender open_id + 路由技能 + 端到端耗时）与 `/chat` API（新增可选 user_id 字段）双通道记录。
- **每用户滑动窗口限流**（app/utils/rate_limiter.py）：`RATE_LIMIT_PER_MINUTE`（默认 30 次/分钟），/chat 超限返回 429，飞书入口回复友好提示；限流器自身异常 fail-open。
- **SLA 指标**：MetricCounter 增加 P95 延迟（最近 200 次样本），/health 输出 llm_calls 与 rag_queries 的 p95_time_ms。
- **每周业务价值报告**：APScheduler 每周一 09:30 生成 Markdown 报告（使用规模/效率收益/技能分布/Top 用户/DAU）保存至 data/reports/。
- **测试**：tests/test_business_metrics.py 覆盖度量汇总、工时换算、内存兜底、报告生成与限流窗口行为（13 个用例）。

---

## [2.0.0] - 2026-08-03（第一次大更新）

### 新增
- **记忆扩容**：会话窗口 10 -> 60 条，工作流加载最近 30 条；消息超过 50 条自动 LLM 摘要（history_summary），25 轮对话可召回首条业务需求。
- **多模态视觉**：飞书图片消息经 VLM 解析为结构化表格，参与 file_analysis_skill 分析。
- **全链路 Token 追踪**：LangChain 回调式记账（token_tracker），router/planner/12 技能/reflect/answer 分技能归属；`/metrics/usage` 输出近 24h 分技能 Token 排行；支持 @timeout 线程池上下文传播。
- **MCP 动态热插拔**：skills_manifest.json 为技能唯一数据源，registry 按 mtime 检测热重载 + version 计数，router 工具/关键词/bind_tools 缓存随版本刷新，新增技能免重启生效。
- **Plan-Execute 规划**：planner 节点为复合指令生成顺序 Step JSON 计划（禁止并行 fan-out），skill_executor 按计划顺序执行并传递上游结果。
- **流式思考链**：收到消息即时回执，路由/规划/执行各阶段推送"思考过程"进度消息。
- **RAG 时间衰减**：文档入库携带 source/last_updated metadata，检索融合后按 exp(-λ·days) 衰减（λ=0.01 可调），新旧矛盾文档取新。
- **飞书审批交互**：高危指令（降价/打折等关键词）触发审批卡片（card.action.trigger WS 回调），批准后后台执行并推送结果；action_log SQLite 动作审计；APPROVAL_ENABLED 开关。
- **API 鉴权**：写接口支持 X-API-Key（API_KEY 环境变量）。
- **集成测试**：tests/integration 6 个流程文件 38 用例（热插拔/记忆/Plan-Execute/RAG 衰减/回归/Token 追踪）。

### 变更
- workflow 节点 7 -> 8（新增 planner）；AgentState 14 -> 16 字段（history_summary、execution_plan）。
- /chat 改为 asyncio.to_thread 执行，不再阻塞事件循环。
- RAG 增量 sync 失败（嵌入维度不匹配等）自动降级全量重建。
- ads_skill LLM 分析失败时降级返回 DB 聚合原始指标。

---

## [1.0.0] - 2026-08-02（稳定基线，标签 v1.0-stable）

### 新增
- **混合检索（Hybrid Search）**：BM25 + FAISS 向量搜索 + RRF 融合 + CrossEncoder 精排（BAAI/bge-reranker-base），向量权重 0.6 / BM25 权重 0.4。
- **LLM-as-Judge 评估**：Routing 准确率评估 + 三维度（relevance / accuracy / completeness）1-5 分制质量评估。
- **Docker 部署**：Dockerfile（python:3.11-slim、非 root 用户、健康检查）+ docker-compose（模型缓存命名卷持久化）。
- **路由 Fallback 机制**：LLM 超时/异常时自动回退到关键词路由，支持交叉验证（关键词置信度 >= 2 时覆盖 LLM 结果）。
- **jieba 中文分词**：BM25 检索使用 jieba 分词，提升中文关键词匹配效果。

### 变更
- RAG 检索从纯 MMR 升级为混合检索 + 精排，MMR 作为最终降级方案。
- 路由系统增加三层递进策略：文件快捷路由 - LLM Tool-Calling - 关键词 Fallback。

---

## [0.9.0] - 2026-07-27 ~ 2026-07-28

### 新增
- **LangGraph 重构**：Agent 编排重构为 LangGraph 多技能并行 + ReAct 反思循环（reflect 节点，最多重试 2 次）。
- **Guardrails 安全防护**：敏感词拦截（block）+ 非电商话题重定向（redirect），在 Agent 调用前拦截。
- **RAG 文档管理**：SHA-256 变更检测、增量/全量更新、查询缓存（TTL=1h, MAX_ENTRIES=200）。
- **记忆持久化**：LocalMemory 双层存储（内存 LRU + SQLite），max_history=10, max_conversations=1000。
- **定时任务**：APScheduler 库存预警检查 + 日报生成。
- **WebSocket 健康监控**：ws_manager 进程管理，最大重启 5 次，冷却 30 秒。
- **CI/CD**：GitHub Actions（flake8 lint + pytest + bandit 安全扫描），Python 3.11。
- **新技能注册**：seo_skill、support_skill、data_analysis_skill。
- **集成测试**：新增 test_integration、test_router_fallback、test_cross_validate 等测试文件。

### 变更
- AgentState 扩展至 14 个字段（新增 skills_to_execute、skill_results、retry_count、reflect_feedback、reflect_decision）。
- SKILL_REGISTRY 扩展至 12 个技能。

### 修复
- langchain_community 导入迁移至独立包（langchain-openai、langchain-huggingface、langchain-text-splitters）。
- FAISS 导入缩进修复。
- CI 测试数据库 fixture 修复。

### 移除
- 私有数据文件从 git 追踪中移除，添加 .gitkeep 保留目录结构。

---

## [0.8.0] - 2026-07-25 ~ 2026-07-26

### 新增
- **群聊/私聊策略**：群聊需 @bot 才响应，私聊直接处理。
- **飞书文件处理**：识别文件消息 - 检查扩展名 - 下载到 data/uploads/ - file_parser_tool 解析。

### 修复
- 修复文件标题可读取但无法下载的问题。
- 修复消息不回复问题。

---

## [0.7.0] - 2026-07-22 ~ 2026-07-23

### 新增
- **文件解析技能**：file_analysis_skill + 飞书文件处理流程。
- **项目结构文档**：完善 README 项目结构说明。

### 移除
- 清理测试阶段临时文件、修复脚本、孤立目录。

---

## [0.6.0] - 2026-07-21

### 新增
- **飞书 WebSocket 集成**：lark-oapi SDK 长连接，注册 im.message.receive_v1 事件。
- **飞书 WebSocket + Agent 对接**：消息接收 - 解析 - Agent 调用 - 回复。
- **CSV/Excel 文件解析**：pandas + openpyxl 数据分析能力。
- **竞品/SEO/客服技能**：competitor_skill、seo_skill、support_skill。
- **文件解析与库存管理增强**。

### 修复
- 中文乱码修复 + qwen3 思考链过滤。
- faiss-cpu 依赖补充。

### 移除
- 临时文件清理。

---

## [0.5.0] - 2026-07-20

### 新增
- **全面智能化升级**：LLM 路由、Function Calling、RAG 知识库、多 Agent 协作、对话记忆、报告生成。
- **飞书集成增强**：API 工具、Webhook 处理器。
- **DashScope API 迁移**：从原始 API 迁移到 DashScope 兼容模式。

### 变更
- 代码质量全面改进与功能增强。

### 修复
- LangChain 1.x 兼容性修复，补充依赖与文档。

---

## [0.1.0] - 2026-07-19

### 新增
- 项目初始化：FastAPI 服务骨架 + /chat 接口。
- 智能化升级基础：LLM 路由、Function Calling、RAG 知识库、多 Agent 协作、对话记忆功能骨架。

---

## 版本约定

- feat: 新功能
- fix: Bug 修复
- refactor: 重构
- docs: 文档更新
- chore: 构建 / 杂项