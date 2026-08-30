# Ecommerce Agent

基于 LangGraph + FastAPI 构建的电商运营智能 Agent 服务，集成飞书 WebSocket 消息接入、RAG 混合检索知识库（时间衰减）、文件解析、多轮对话记忆（60 条热窗口 + SQLite 全量归档 + LLM 摘要持久化）、Guardrails 安全防护、MCP 动态技能热插拔、Plan-Execute 顺序规划、高危操作飞书审批（问价咨询与调价执行严格分离：调价经"模拟验证 → 人工审批 → 决策登记 → 商家后台手动改价"链路，Agent 不直接操作平台）、回滚登记持久化（重启不丢安全保证）、多模态图片解析、全链路 Token 追踪等功能。用户通过飞书发送自然语言，Agent 自动识别意图、路由到对应技能、调用工具完成任务。

---

## 目录

1. [系统架构](#1-系统架构)
2. [LangGraph 工作流](#2-langgraph-工作流)
3. [路由机制](#3-路由机制)
4. [技能列表](#4-技能列表13-个)
5. [RAG 知识库系统](#5-rag-知识库系统)
6. [Guardrails 安全防护](#6-guardrails-安全防护)
7. [记忆系统](#7-记忆系统)
8. [飞书集成](#8-飞书集成)
9. [文件解析](#9-文件解析)
10. [定时任务](#10-定时任务)
11. [项目结构](#11-项目结构)
12. [快速开始](#12-快速开始)
    - [一键安装（推荐）](#121-一键安装推荐)
    - [手动安装](#122-手动安装)
    - [Docker 部署](#123-docker-部署)
13. [Docker 部署详解](#13-docker-部署详解)
14. [API 接口](#14-api-接口)
15. [飞书开放平台配置](#15-飞书开放平台配置)
16. [单元测试](#16-单元测试)
17. [CI/CD](#17-cicd)
18. [配置说明](#18-配置说明)
19. [License](#19-license)

---

## 1. 系统架构

### 完整数据流

```
飞书用户发送消息
    |
    v
feishu_ws.py --- WebSocket 长连接 (lark-oapi SDK)
    |              +- 群聊: 需 @bot 才响应
    |              +- 私聊: 直接处理
    |              +- 文件消息: 检查扩展名 -> 下载到 data/uploads/ -> 解析
    v
guardrails.check_input() --- 安全拦截
    |  +- block: 敏感词 -> 直接拒绝，不调用 Agent
    |  +- redirect: 非电商话题 -> 引导回复
    |  +- allow: 正常放行
    v
LangGraph agent.invoke() --- 状态机工作流
    |
    +- load_history    加载最近 30 条对话历史 + 长对话摘要
    +- load_file       解析上传文件（若有）
    +- router          意图识别 + 技能路由（三层递进，工具清单随 manifest 热更新）
    +- planner         复合指令生成顺序执行计划（Plan-Execute）
    +- skill_executor  按计划顺序执行 1~N 个技能（高危操作走审批门）
    +- reflect         ReAct 反思：LLM 判断结果是否充分
    |     +- insufficient -> 回到 router 重新路由（最多 2 次）
    +- answer          单结果直接提取 / 多结果 LLM 综合
    +- save_history    持久化对话到 LocalMemory
    |
    v
feishu_tool.reply_message() --- 回复用户
```

### 核心技术栈

| 类别 | 技术 | 说明 |
|------|------|------|
| Agent 编排 | LangGraph 0.2+ | 状态机工作流，条件边 + ReAct 反思循环 |
| LLM 框架 | LangChain 0.2+ | StructuredTool、消息处理、bind_tools |
| LLM 模型 | deepseek-v4-pro | 通过 DashScope OpenAI 兼容接口调用 |
| Web 框架 | FastAPI + Uvicorn | HTTP 接口、CORS、全局异常处理 |
| 向量检索 | FAISS + BM25 + CrossEncoder | 混合检索 + RRF 融合 + 精排 |
| Embedding | sentence-transformers | 本地 paraphrase-multilingual-MiniLM-L12-v2 |
| 文档管理 | SHA-256 + 增量更新 | 变更检测、查询缓存 |
| 飞书集成 | lark-oapi | WebSocket 长连接、AES 消息解密 |
| 数据存储 | SQLite(WAL) + SQLAlchemy | 对话全量归档、摘要持久化、回滚登记落库；WAL + busy timeout 支撑多线程并发写 |
| 文件解析 | pandas, openpyxl, PyPDF2, python-docx | Excel/CSV/PDF/Word |
| 安全防护 | Guardrails + pycryptodome | 输入检测、飞书消息 AES 解密 |
| 定时任务 | APScheduler | 库存预警、日报生成 |
| 中文分词 | jieba | BM25 检索分词 |
| 技能注册 | MCP manifest | skills_manifest.json 动态热插拔（mtime 检测，免重启） |
| 可观测性 | Token 回调记账 | router/planner/技能/reflect/answer 分技能统计 |
| 审批流 | 飞书交互卡片 | card.action.trigger 回调 + 后台执行 + SQLite 动作日志 |
| 业务度量 | BusinessTaskLog | 按用户记录任务（user_id/技能/成败/耗时），/metrics/business 输出活跃用户、成功率与节省工时估算 |
| 流量防护 | 滑动窗口限流 | 按用户 RATE_LIMIT_PER_MINUTE 限流，/chat 返回 429，飞书入口友好提示 |
| 多模态 | VLM | 图片解析为结构化表格（file_analysis_skill） |
| LLM 容错 | invoke_with_recovery | 上下文超限裁剪重试 + 限流指数退避 + 备用模型自动切换 |
| 持久记忆 | persistent_memory | 从用户输入提取长期记忆，注入 system prompt 增强个性化 |
| Hooks | hooks.py | PreToolUse / PostToolUse / UserPromptSubmit 生命周期钩子 |
| 路由加速 | 关键词快速路径 + 结果缓存 | 高置信关键词命中跳过 LLM（≈0ms），temperature=0 路由结果缓存复用 |

---

## 2. LangGraph 工作流

### 节点定义（8 个节点）

| 节点 | 职责 |
|------|------|
| load_history | 从 LocalMemory 加载最近 30 条对话历史 + 长对话摘要（history_summary） |
| load_file | 若有文件路径，调用 file_parser_tool 解析文件 |
| router | 意图识别 + 技能路由，输出 skills_to_execute 列表（支持多技能） |
| planner | 多技能时生成顺序执行计划 execution_plan（Step JSON，禁止并行 fan-out）；单技能跳过 |
| skill_executor | 按 execution_plan 顺序执行技能；定价区分问价咨询（只给建议）与调价指令（明示指令走审批门，批准后登记调价决策），高危指令非阻塞挂起 |
| reflect | ReAct 反思：LLM 判断技能结果是否充分 |
| answer | 单结果直接提取；多结果调用 LLM 综合生成连贯回答 |
| save_history | 将用户输入和最终回答写入 LocalMemory |

### 条件边

- reflect_decision == "insufficient" -> 回到 router，携带 reflect_feedback 指导重新路由
- reflect_decision == "sufficient" -> 进入 answer
- 短路规则：file_analysis_skill 和 rag_skill 跳过 reflect 直接 sufficient
- 防死循环：retry_count >= MAX_RETRIES (2) 时强制 sufficient
- 容错：reflect LLM 超时 20 秒，异常时 fail-open 为 sufficient

### AgentState 定义（18 个字段）

user_input, conversation_id, history, tool_result, answer, intent, token_usage, file_path, file_content, skills_to_execute, skill_results, retry_count, reflect_feedback, reflect_decision, history_summary, execution_plan, todo_list, todo_last_updated_round

---

## 3. 路由机制

路由采用四层递进策略，确保高可用：

### 第一层：文件快捷路由

若 file_path 和 file_content 都存在，且用户输入为空/以 [文件] 开头/包含文件相关关键词（解析、分析、查看、解读等），直接路由到 file_analysis_skill，跳过 LLM 调用。

### 第二层：定价指令确定性快路径

明示调价指令（目标价/涨跌幅/折扣）经 `pricing_skill.has_explicit_directive` 结构化判别命中后，直接路由到 pricing_skill，跳过 LLM——**安全关键路径的路由不依赖 LLM 能力**（弱模型/降级模式下"SKU-A001改价到99"曾被误路由到商品分析技能，调价审批门被整条绕过）。判别基于指令结构解析而非裸关键词：竞品语境（"竞品把价格杀到99了"）、咨询句式（"要不要降价"）、创作素材（"写降价文案"）等歧义输入不触发；其余技能关键词 conf>=2 的复合指令交回 LLM/规划器。可通过 `ROUTER_PRICING_DIRECTIVE_FAST_PATH` 关闭。

### 第三层：LLM Tool-Calling

将 13 个技能封装为 StructuredTool，通过 llm.bind_tools(tools) 让 LLM 以 function calling 方式选择技能。支持多技能选择。超时 30 秒。

### 第四层：交叉验证 + Keyword Fallback

- 交叉验证：LLM 选择后，用关键词评分验证。若关键词最高分技能与 LLM 不同且置信度 >= 2，则关键词结果优先。
- Keyword Fallback：LLM 调用超时或异常时，使用 KEYWORD_RULES 进行关键词匹配。
- 最终 Fallback：关键词也无匹配 -> intent = "unknown" -> LLM 闲聊兜底。

### 性能优化

- **关键词快速路径**：高置信关键词唯一命中（conf >= 2 且无并列）时跳过 LLM，路由耗时 ≈ 0ms。反思重试轮不走快速路径。
- **路由结果缓存**：temperature=0 下路由结果确定性保证，相同输入+相同会话上下文直接复用缓存（TTL 600s，MAXSIZE 512）。manifest 版本纳入缓存 key，热更新后旧缓存自动失效。

### 动态热插拔（MCP manifest）

技能清单以 skills_manifest.json 为唯一数据源（name/description/keywords/module/function）。registry 每次路由前检测 manifest 文件 mtime，变化则重载并递增 version；router 按 version 刷新工具列表、关键词规则与 bind_tools 缓存。新增/修改技能无需重启服务即可生效。
---

## 4. 技能列表（13 个）

| # | 技能名 | 功能 | 触发关键词 | 实现方式 |
|---|--------|------|-----------|---------|
| 1 | product_skill | 商品销售数据分析、趋势、利润率、SKU 对比 | 商品、销量、SKU、评价、卖得 | DB 查询 + 趋势/利润计算 + LLM 报告 |
| 2 | ads_skill | 广告投放效果、ROI/CTR/CPC、渠道对比 | 广告、投放、ROI、推广、花费、渠道 | DB 查询 + 指标计算 + 平台对比 + LLM |
| 3 | inventory_skill | 库存预警、补货建议、周转分析 | 库存、补货、预警、周转、缺货 | DB 全量查询 + 按品类阈值检测 |
| 4 | competitor_skill | 竞品分析、市场竞争情报 | 竞品、竞争、对手、市场情报 | LLM 直接回答（截断 500 字符） |
| 5 | report_skill | 运营报告生成并保存为 Markdown | 报告、周报、月报、汇总 | LLM 总结 + file_tool 写入 reports/ |
| 6 | rag_skill | 知识库检索增强问答 | 规则、佣金、上架、平台规则、怎么算 | 混合检索 + LLM 生成 |
| 7 | seo_skill | SEO 优化、关键词研究、标题优化 | SEO、关键词、搜索量、标题优化、长尾词 | keyword_tool 查询 + LLM 分析 |
| 8 | support_skill | 客服：订单查询、退换货、物流、售后 | 订单、退款、退货、售后、客服、物流 | 意图分类 + ticket_tool + LLM |
| 9 | data_analysis_skill | 深度数据分析、趋势、异常检测 | 趋势、异常、同比、环比、统计 | DB 查询 + 基础统计 + LLM 专业分析 |
| 10 | file_analysis_skill | 文件解析分析报告 | 解析文件、分析文件、这个表格、这份数据 | 已解析 file_content + LLM 结构化报告 |
| 11 | help_skill | 使用帮助、功能介绍 | 帮助、你能做什么、功能、怎么用 | HELP_PROMPT + LLM |
| 12 | listing | Listing 生成：商品图片 → 多语言合规标题/五点描述/商品描述/后台关键词（含违禁词合规审核） | listing、标题、描述、商品详情、重新生成 | 多模态图片识别 + 平台规则 + 合规审核 |
| 13 | pricing_skill | L4 智能定价（问价/调价分离）：问价咨询（"卖多少钱合适"）与"我降到X行不行"均输出蒙特卡洛沙盒测算建议，不改价；明示调价指令（目标价/涨跌幅/折扣）经确定性快路径直达本技能，先跑沙盒验证再发审批卡片，点批准后**登记调价决策并引导在电商平台商家后台手动改价**（Agent 不直接操作平台）；批量调价直接拒绝 | 定价、活动价、调价、卖多少钱、降价 20%、改价到 99、打个八八折 | profit_model + solver_engine 蒙特卡洛模拟 + 审批门 + 决策登记 |

库存预警阈值（按品类）：electronics: 50, clothing: 100, food: 100, beauty: 200, 默认: 100

---

## 5. RAG 知识库系统

### 5.1 文档分块策略

| 参数 | 值 |
|------|------|
| Splitter | RecursiveCharacterTextSplitter（langchain_text_splitters） |
| chunk_size | 512 |
| chunk_overlap | 100 |
| separators | ["\n\n", "\n", "。", "！", "？", "；", " ", ""] |

递归切分优先级：段落(\n\n) -> 行(\n) -> 中文句号 -> 中文感叹号 -> 中文问号 -> 中文分号 -> 空格 -> 逐字符。分隔符列表包含中文标点，对中文电商文档友好。

### 5.2 Embedding 模型（三级降级）

| 优先级 | 模型 | 条件 | 说明 |
|--------|------|------|------|
| 1 | paraphrase-multilingual-MiniLM-L12-v2 | USE_LOCAL_EMBEDDING=true | 本地 HuggingFace，CPU，normalize_embeddings=True |
| 2 | text-embedding-v4 | 本地模型不可用 | DashScope 阿里云远程 API |
| 3 | MockEmbedding | 全部不可用 | 768 维全零向量，仅测试兜底 |

- 加载超时保护：300 秒
- 本地模型缓存路径：~/.cache/huggingface/hub

### 5.3 向量库

- FAISS（langchain_community.vectorstores.FAISS）
- 持久化路径：./data/vectorstore/faiss_index
- 支持本地加载已有索引（FAISS.load_local），不存在时从文本创建

### 5.4 混合检索（四步流程）

1. FAISS 向量搜索：similarity_search(query, k=k*3)，按排名赋分 score = 1/(rank+1)
2. BM25 关键词搜索：jieba 分词 + BM25Okapi，获取 BM25 原始分数
3. RRF 融合（Reciprocal Rank Fusion）：
   - 公式: score = weight * 1/(k + rank + 1)
   - 向量权重 = 0.6 (HYBRID_ALPHA)，BM25 权重 = 0.4
   - RRF 常数 k = 60
   - 同文档两路分数累加，source 标记 "hybrid"，按融合分数降序排列
4. CrossEncoder 精排：BAAI/bge-reranker-base，构造 (query, document) 对打分重排，离线模式加载，精排后取 RERANK_TOP_K = 5 条

### 5.5 降级策略

| 故障场景 | 降级行为 |
|---------|---------|
| BM25 依赖缺失 | 纯向量搜索 |
| Rerank 模型不可用 | 跳过精排，直接截取 top-k |
| 混合搜索整体失败 | 回退 MMR：fetch_k=10, lambda_mult=0.5, k=3 |
| MMR 也失败 | 回退 similarity_search(query, k=k) |

### 5.6 文档管理与变更检测

- 扫描 data/documents/ (.txt/.md) -> 计算 SHA-256 哈希 -> 对比 doc_hashes.json
- 新文件 -> 增量更新（仅分块新文档 + add_documents）
- 哈希不同/文件消失 -> 全量重建（删除旧索引 + FAISS.from_documents）
- 无变更 -> 跳过（仅重建内存 BM25 索引）
- 任何变更后清空查询缓存
- 自动同步间隔：60 秒
- 文档集签名：所有哈希 JSON 序列化后 SHA-256 前 16 位

### 5.7 查询缓存

| 参数 | 值 |
|------|------|
| 缓存文件 | ./data/vectorstore/query_cache.json |
| TTL | 3600 秒（1 小时） |
| MAX_ENTRIES | 200（超出按时间戳淘汰最旧） |
| 缓存 Key | SHA-256(query + ":" + doc_signature) |
| 失效条件 | 超过 TTL / 文档签名变化 |

### 5.8 检索后生成

1. 调用混合搜索获取 top-3 文档
2. 无结果 -> 直接调用 LLM 回答（无上下文）
3. 有结果 -> 拼接为 context，构造 prompt 让 LLM 基于上下文回答
4. 后处理：若 LLM 输出包含 think 标签，提取其后内容（适配 DeepSeek-R1 思考链）

### 5.9 RAG 评估

关键词召回率评估（app/rag/eval/evaluate_rag.py）：
- 测试集：20 个电商平台规则问题，4 个类别（佣金/上架/运营/营销，每类 5 题）
- 每题预设 3 个预期关键词，检索 top-3 文档，检查关键词命中

评估结果：
- Total questions: 20
- Relevant results: 20/20 (100%)
- Average recall: 78%
- Average latency: 11ms

LLM-as-Judge 评估（app/eval/llm_judge.py）：
- Routing 评估：7 个问题覆盖 7 个技能路由，测路由准确率 + 延迟
- Judge 评估：LLM 打分 1-5 分，三个维度（relevance / accuracy / completeness）

### 5.10 时间衰减排序

文档入库时携带 metadata（source=文件名、last_updated=文件修改时间 ISO）。混合检索融合后对每个结果应用指数时间衰减：

- final_score = rrf_score * exp(-TIME_DECAY_LAMBDA * days_ago)，TIME_DECAY_LAMBDA=0.01（环境变量可调）
- 30 天前的文档权重约 74%，90 天前约 41%
- 新旧文档内容矛盾时，新文档自动胜出
- 缺少时间戳的结果不衰减

---

## 6. Guardrails 安全防护

纯关键词匹配，在飞书消息处理层（Agent 调用之前）拦截：

| 类型 | 关键词 | 动作 |
|------|--------|------|
| BLOCKED（拦截） | 政治、政府、颠覆、反动、爆炸、杀人、毒品、武器、赌博、诈骗、盗版、黑客 | 直接返回拒绝消息 |
| REDIRECT（重定向） | 看病、医疗、股票、基金 | 返回引导消息 |
| ALLOW（放行） | 其他所有输入 | 正常进入 Agent 流程 |

---

## 7. 记忆系统

LocalMemory 双层存储架构（归档式持久化）：

| 层 | 实现 | 说明 |
|----|------|------|
| 内存层 | OrderedDict + LRU 淘汰 | 超过 1000 个会话时淘汰最久未用的；每会话仅保留 60 条热窗口 |
| 持久层 | SQLite（SQLAlchemy，WAL 模式） | 表 Conversation，写入时同步，**全量归档永不物理删除**；读取时懒加载最近 60 条（按 id 倒序取最新窗口） |

| 参数 | 值 |
|------|------|
| max_history | 60 条/会话（内存热窗口） |
| max_conversations | 1000 |
| 工作流实际使用 | 最近 30 条 + 历史摘要 |
| 自动摘要 | 消息超过 50 条时，旧消息 LLM 压缩为摘要（history_summary），**持久化到 conversation_summaries 表，跨重启保留** |
| DB 内容截断 | 20000 字符（超出截断并告警） |
| 消息元数据 | save_history 同时写入 intent / skill / token_usage，支撑审计与用量回溯 |

每条消息格式：{"role": "user"/"assistant", "content": str, "timestamp": ISO时间}

### SQLite 持久化层特性

| 特性 | 说明 |
|------|------|
| WAL 模式 | 连接时自动启用 `PRAGMA journal_mode=WAL`，读写互不阻塞，支撑 workflow / APScheduler / WS 回调多线程并发写 |
| busy timeout | 30 秒，并发写冲突时等待而非抛 "database is locked" |
| 归档式历史 | conversations 表保留全量对话（支持审计/回溯），窗口裁剪仅作用于内存层 |
| 摘要持久化 | conversation_summaries 表（conversation_id 唯一，upsert），重启后长对话压缩历史不丢失 |
| 回滚登记 | pending_actions 表记录 L4 待确认动作（old_values 等），重启后自动恢复，1 小时自动回滚保证不中断；`ROLLBACK_PERSISTENCE_ENABLED` 可关闭 |
| 日志保留期 | token_usage_logs / business_task_logs 每日 03:00 清理超期记录（LOG_RETENTION_DAYS，默认 90 天） |

---

## 8. 飞书集成

- 连接方式：lark-oapi SDK WebSocket 长连接（非 Webhook）
- 并发模型：消息队列 queue.Queue + ThreadPoolExecutor（默认 3 worker，WS_MAX_WORKERS 可调）
- 群聊策略：需 @bot 才响应；私聊直接处理
- 文件消息：检查扩展名（文档 .xlsx/.xls/.csv/.pdf/.docx，图片 .jpg/.jpeg/.png/.webp 走多模态解析）-> 下载到 data/uploads/ -> 解析
- 消息解密：AES 解密（pycryptodome）
- 进程管理：ws_manager 管理 WebSocket 子进程，最大重启 5 次，冷却 30 秒
- 流式体验：收到消息立即回执"已收到，正在思考..."，路由/规划/执行各阶段推送"思考过程"进度消息
- 多模态：图片消息下载后经 VLM 解析为结构化表格内容参与分析
- 审批交互：高危操作发送交互卡片（批准/拒绝按钮），card.action.trigger 回调（WS 长连接事件帧）3 秒内响应，批准后后台线程处理并推送回执（调价动作登记决策并附商家后台手动执行引导，其余动作执行并推送结果）

---

## 9. 文件解析

| 格式 | 解析库 | 说明 |
|------|--------|------|
| CSV | pandas | pd.read_csv |
| Excel (.xlsx) | pandas + openpyxl | pd.read_excel |
| Excel (.xls) | pandas + xlrd | pd.read_excel |
| PDF | PyPDF2 | PdfReader 逐页提取文本 |
| Word (.docx) | python-docx | 逐段落提取文本 |

- 自动提取统计摘要：均值、最大值、最小值、标准差
- 路径穿越防护：FileTool 拦截 ../../ 等非法路径

---

## 10. 定时任务

基于 APScheduler 的后台调度器：

| 任务 | 说明 |
|------|------|
| inventory_check | 库存预警检查，按品类阈值检测低库存 |
| daily_report | 日报生成 |
| weekly_business_report | 每周一 09:30 生成业务价值报告（活跃用户/任务量/节省工时），保存到 data/reports/ |
| log_retention_cleanup | 每日 03:00 清理超过 LOG_RETENTION_DAYS（默认 90 天）的 token_usage_logs / business_task_logs，防止日志表无限增长 |
---

## 11. 项目结构

```
Agent_feishu/
├── app/
│   ├── agent/                    # Agent 核心
│   │   ├── router.py             # 意图路由（LLM + 关键词 + 交叉验证 + fallback）
│   │   ├── workflow.py           # LangGraph 状态机（8 节点 + 条件边）
│   │   └── state.py              # AgentState 定义（18 字段, MAX_RETRIES=2）
│   ├── api/
│   │   └── feishu.py             # 飞书路由（webhook 事件回调 / message 主动发送 / chat 对话）
│   ├── eval/
│   │   └── llm_judge.py          # LLM-as-Judge 评估
│   ├── memory/
│   │   ├── local_memory.py       # 双层记忆（内存 LRU + SQLite 持久化）
│   │   └── persistent_memory.py  # 持久记忆（从用户输入提取长期记忆 + 检索注入）
│   ├── models/
│   │   ├── database.py           # SQLAlchemy 引擎（SQLite WAL + busy timeout）
│   │   └── models.py             # 8 张 ORM 表（含 ConversationSummary 摘要持久化、PendingAction 回滚登记）
│   ├── monitoring/
│   │   ├── stats.py              # 监控统计
│   │   └── business.py           # 业务价值度量（DAU/成功率/节省工时）
│   ├── rag/
│   │   ├── vectorstore.py        # FAISS + 分块 + Embedding 三级降级
│   │   ├── hybrid_search.py      # BM25 + 向量 + RRF 融合 + CrossEncoder 精排
│   │   ├── retriever.py          # 检索 + LLM 生成
│   │   ├── doc_manager.py        # 文档 CRUD + SHA-256 变更检测 + 查询缓存
│   │   └── eval/
│   │       └── evaluate_rag.py   # 20 题关键词召回率评估
│   ├── skills/                   # 13 个业务技能
│   ├── optimizer/                # L4 损益优化层（定价模型/求解器/冲突仲裁）
│   │   ├── profit_model.py       # 利润/需求弹性模型
│   │   ├── solver_engine.py      # 蒙特卡洛/约束求解引擎
│   │   ├── conflict_resolver.py  # 多目标冲突检测与仲裁
│   │   └── api.py                # 优化层 HTTP 路由
│   ├── sentinel/                 # L4 市场哨兵（竞品监控/触发引擎）
│   │   ├── crawler_base.py       # 爬虫基类（curl_cffi 指纹伪装降级 httpx）
│   │   ├── trigger_engine.py     # 价格/差评触发引擎
│   │   └── event_bus.py          # 事件总线（内存/redis 可选）
│   ├── executor/                 # L4 动作执行层（审批门 + 回滚）
│   │   ├── action_verifier.py    # 高危动作校验与审批门
│   │   ├── platform_adapter.py   # 店铺平台适配器（mock/真实）
│   │   └── rollback_manager.py   # 动作回滚管理（登记落库 pending_actions，重启可恢复）
│   ├── tasks/
│   │   └── scheduler.py          # APScheduler 定时任务（含日志保留期清理）
│   ├── tools/
│   │   ├── feishu_ws.py          # 飞书 WebSocket 长连接
│   │   ├── feishu_tool.py        # 飞书 API 封装
│   │   ├── file_parser_tool.py   # 文件解析（CSV/Excel/PDF/Word）
│   │   ├── file_tool.py          # 文件读写（路径穿越防护）
│   │   ├── guardrails.py         # 输入安全检测
│   │   ├── database_tool.py      # 数据库查询
│   │   ├── keyword_tool.py       # SEO 关键词分析
│   │   ├── ticket_tool.py        # 工单管理
│   │   └── ws_manager.py         # WebSocket 进程管理
│   ├── mcp_server/
│   │   └── registry.py           # MCP 技能注册中心（manifest 热加载 + version 计数）
│   ├── utils/
│   │   ├── timeout.py            # 超时装饰器（线程上下文传播）
│   │   ├── token_tracker.py      # Token 归属记账（thread-local + LangChain 回调）
│   │   ├── approval.py           # 审批管理器（高危关键词门控 + 挂起执行）
│   │   ├── action_log.py         # 审批动作日志（SQLite）
│   │   ├── security.py           # API 鉴权 + 注入检测
│   │   ├── tracing.py            # 节点耗时追踪
│   │   ├── rate_limiter.py       # 滑动窗口限流器（每用户每分钟阈值）
│   │   ├── llm_retry.py          # LLM 调用错误恢复（分类+退避+备用模型切换）
│   │   ├── hooks.py              # 生命周期钩子（PreToolUse/PostToolUse/UserPromptSubmit）
│   │   ├── default_hooks.py      # 默认钩子注册
│   │   ├── todo_manager.py       # Plan-Execute 任务进度追踪
│   │   └── background_tasks.py   # 后台任务管理
│   ├── config.py                 # 配置管理（环境变量）
│   ├── prompts.py                # Prompt 模板
│   └── main.py                   # FastAPI 入口
├── data/
│   ├── documents/                # 知识库文档（.txt/.md）
│   ├── uploads/                  # 上传文件
│   └── vectorstore/              # FAISS 索引 + 哈希注册表 + 查询缓存
├── tests/                        # 单元测试 + tests/integration 集成流程（详见第 16 节）
├── scripts/
│   └── init_db.py                # 数据库初始化
├── .github/workflows/
│   └── ci.yml                    # GitHub Actions CI
├── setup.sh                      # 一键安装脚本（Linux / macOS）
├── setup.bat                     # 一键安装脚本（Windows）
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example                  # 环境变量模板
├── .gitignore
├── requirements.txt
├── skills_manifest.json          # 技能清单（MCP 动态注册数据源，可热编辑）
├── CHANGELOG.md
└── README.md
```

---

## 12. 快速开始

### 前置条件

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| Python | 3.11 | 必须 |
| pip / uv | 最新 | Python 包管理器 |
| Git | 任意 | 拉取代码 |
| 系统库 | libopenblas-dev | FAISS 向量库需要（Ubuntu: `apt install libopenblas-dev`，CentOS: `yum install openblas-devel`，macOS: `brew install openblas`） |

> 支持平台：Linux（Ubuntu/CentOS 等）、macOS、Windows 原生、WSL、Docker

### 12.1 一键安装（推荐）

提供一键安装脚本，自动完成环境检测、虚拟环境创建、依赖安装、数据库初始化等全部步骤。

**Linux / macOS / WSL：**

```bash
chmod +x setup.sh
./setup.sh
```

**Windows：**

双击运行 `setup.bat`

脚本会自动完成：
1. 检测 Python 3.11+ 版本
2. 检测系统依赖（gcc、libopenblas），缺失时给出安装命令提示
3. 创建虚拟环境（优先 conda，回退 venv）
4. 安装 Python 依赖（优先 uv，回退 pip）
5. 从 `.env.example` 复制 `.env`，引导填写 API 密钥等配置
6. 初始化数据库 + 种子数据
7. 创建数据目录
8. 生成快捷启动脚本 `start.sh` / `start.bat`

**安装完成后启动：**

```bash
# Linux / macOS / WSL
./start.sh          # 开发模式（热重载）
./start.sh prod     # 生产模式

# Windows
start.bat           # 开发模式
start.bat prod      # 生产模式
```

### 12.2 手动安装

如果一键安装脚本不满足需求，可按以下步骤手动安装。

#### 12.2.1 创建环境

```bash
conda create -n feishuagent python=3.11
conda activate feishuagent
# 或者使用 venv:
# python3.11 -m venv .venv && source .venv/bin/activate
```

#### 12.2.2 安装依赖

```bash
# 方式一：pip
pip install -r requirements.txt

# 方式二：uv（更快的依赖解析与安装）
uv pip install -r requirements.txt
```

#### 12.2.3 配置环境变量

复制 .env.example 为 .env 并填写 LLM_API_KEY、FEISHU_APP_ID、FEISHU_APP_SECRET、API_KEY 等必填项。

```bash
cp .env.example .env
# 编辑 .env，至少填写以下必填项：
#   LLM_API_KEY       - 大模型 API 密钥（DashScope/OpenAI）
#   FEISHU_APP_ID     - 飞书应用 ID
#   FEISHU_APP_SECRET - 飞书应用密钥
#   API_KEY           - HTTP 接口鉴权密钥
```

#### 12.2.4 初始化数据库

```bash
python scripts/init_db.py
```

#### 12.2.5 启动服务

```bash
# 开发模式
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 生产模式
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

#### 12.2.6 RAG 评估（可选）

```bash
python -m app.rag.eval.evaluate_rag
```

### 12.3 Docker 部署

无需安装 Python 环境，只需 Docker + Docker Compose。

```bash
docker compose up -d --build
docker compose logs -f
```

停止服务：

```bash
docker compose down
```

> 详细说明见 [第 13 节](#13-docker-部署详解)

---

## 13. Docker 部署详解

### Dockerfile 特性

- 基础镜像：python:3.11-slim
- 系统依赖：build-essential、libopenblas-dev（FAISS 需要）
- 非 root 用户：appuser
- 健康检查：curl -f http://localhost:8000/health（30s 间隔，60s 启动宽限）
- 环境变量：HF_HUB_OFFLINE=1（离线模式，需预缓存模型）

### 部署命令

```bash
docker compose up -d --build
docker compose logs -f
docker compose down
```

### docker-compose 配置

- 端口映射：8000:8000
- 环境变量：env_file: .env；compose environment 覆盖 `DATABASE_URL=sqlite:////app/db/feishu_agent.db`（优先级高于 env_file）
- 数据卷：./data:/app/data（知识库文档 + 向量索引）
- 数据库卷：db_data 命名卷挂载 /app/db（SQLite 库 + WAL 边车文件，容器重建/升级不丢归档对话、摘要与回滚登记）
- 记忆卷：memory_data 命名卷挂载 /app/.memory（持久记忆 Markdown，内容私密不入库）
- 模型缓存：model_cache 命名卷（持久化 HuggingFace 模型）
- 重启策略：unless-stopped

> 数据库与记忆目录使用命名卷而非 bind mount：首次使用时自动继承镜像内目录的 appuser 属主，避免宿主机目录缺失时 Docker 以 root 创建导致非 root 容器写失败。备份可用 `docker compose cp app:/app/db/feishu_agent.db ./backup.db`（建议先停服或使用 SQLite 在线备份）。

> 注意：首次启动需确保 HuggingFace 模型已缓存，否则 HF_HUB_OFFLINE=1 会导致降级到 DashScope 远程 Embedding。

---

## 14. API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | / | 服务状态 |
| GET | /health | 健康检查（含调用计数与 P95 延迟） |
| GET | /health/details | 健康详情 |
| POST | /chat | 主聊天接口 |
| POST | /rag/query | RAG 查询 |
| GET | /ws/status | WebSocket 状态 |
| GET | /tasks/status | 定时任务状态 |
| GET | /documents | 列出文档 |
| POST | /documents | 添加文档 |
| DELETE | /documents/{name} | 删除文档 |
| POST | /rag/sync | 同步向量库（?force=true 全量重建） |
| GET | /rag/status | RAG 状态 |
| GET | /metrics/usage | 分技能 Token 消耗统计（近 24h 排行） |
| GET | /metrics/business | 业务价值指标：活跃用户数/任务量/成功率/节省工时估算（?days=N，默认 7） |
| GET | /health/jingang | 金刚消耗监控 |
| POST | /approval/{approval_id}/resolve | 审批单批准/拒绝（?approved=true/false） |
| POST | /optimize/pricing | L4 智能定价（蒙特卡洛模拟） |
| POST | /optimize/resolve-conflict | L4 多目标冲突检测与仲裁 |
| POST | /optimize/choose-option | L4 决策看板点选（方案 A/B） |
| POST | /sentinel/check | L4 市场哨兵触发检查 |
| POST | /executor/confirm/{action_id} | L4 执行器确认动作 |
| GET | /executor/status/{action_id} | L4 执行器动作状态查询 |
| POST | /feishu/webhook | 飞书事件回调（url_verification + im.message.receive_v1） |
| POST | /feishu/message | 主动发送飞书消息（chat_id + content） |
| POST | /feishu/chat | 飞书渠道对话（直接调用 Agent 工作流） |

> /chat、/rag/query、/approval 等写接口受 X-API-Key 鉴权保护（环境变量 API_KEY 配置）。**默认拒绝（fail-closed）**：未配置 API_KEY 时这些接口返回 503，配置后需携带匹配的 `X-API-Key` 请求头，避免服务在未鉴权状态下暴露。

---

## 15. 飞书开放平台配置

1. 访问 https://open.feishu.cn/app 创建企业自建应用
2. 添加权限：doc:document:readonly, im:message:readonly, im:resource:readonly, im:message:send_as_bot
3. 配置事件订阅：选择长连接模式，订阅 im.message.receive_v1
4. 配置卡片回调：回调配置选择"使用长连接接收"，并在"已订阅的回调"中添加卡片回传交互（card.action.trigger），否则审批按钮点击报 200340
5. 设置 Encrypt Key 和 Verification Token
6. 发布应用
---

## 16. 单元测试

共 47 个测试文件、520 个用例（517 passed / 3 skipped，含 tests/integration 6 个端到端流程文件），覆盖路由（含定价指令确定性快路径）、工作流、记忆、安全、工具、调度、热插拔、Plan-Execute、RAG 衰减、Token 追踪（含未归属调用兜底记账）、定价（问价咨询/调价指令分离 + 决策登记）/冲突仲裁/执行器/市场哨兵（L4）、多模态、注入防御、业务度量与限流、压力边界等核心模块。

### 共享 Fixture（conftest.py）

| Fixture | 作用域 | 说明 |
|---------|--------|------|
| setup_test_database | session, autouse | 创建 product_sales / ads_performance 表 + 种子数据 |
| tmp_dir | function | 临时目录，测试后自动清理 |
| file_tool | function | 沙箱化 FileTool（基于 tmp_dir） |

### test_business_metrics.py — 业务度量与限流器（10 个测试）

- TestBusinessMetricsRecord (4): 汇总计数、节省工时仅计成功任务、DAU 与 Top 用户、技能分布
- TestBusinessMetricsMemoryFallback (2): DB 不可用内存降级、价值报告章节完整性
- TestRateLimiter (4): 阈值限流、remaining/reset、窗口滑过、环境变量默认值

### test_file_tool.py — 文件工具（13 个测试）

- TestPathTraversal (7): 正常路径允许、../../etc/passwd 读取拦截、路径穿越写入/删除/列目录/追加拦截
- TestFileOperations (6): 文本/JSON/CSV 格式写入读取、列目录、删除文件、追加内容

### test_guardrails.py — 安全护栏（5 个测试）

空输入允许、正常电商查询允许、危险关键词拦截（"制造爆炸" -> block）、非电商话题重定向（"股票走势" -> redirect）、批量电商查询允许

### test_integration.py — 多模块集成（18 个测试）

- TestFullWorkflowTextMessage (1): Mock LLM 执行完整 agent workflow
- TestSkillRegistryCompleteness (3): 13 个技能注册完整性、router tools 一致性
- TestGuardrailsIntegration (4): 安全/危险/离题/空输入批量验证
- TestMemoryPersistenceIntegration (3): 存取、会话隔离、max_history 裁剪
- TestRouterToolBinding (2): 13 个 tools 绑定、LLM tool_call 解析
- TestTicketToolCrudFlow (1): 工单完整生命周期
- TestKeywordToolAnalysisFlow (4): 已知/未知关键词、热门词、长尾词
- TestFileParserIntegration (3): CSV 解析、缺失文件、摘要格式
- TestReflectNodeSufficient (2): reflect 决策、file_skill 跳过
- TestAnswerNode (2): 单结果提取、多结果 LLM 综合

### test_memory.py — 会话记忆（12 个测试）

- TestLocalMemory (7): 添加获取、最近 N 条、裁剪、清除、空会话、多会话、格式化
- TestMemoryLRU (4): LRU 淘汰、touch 更新、统计、未达上限不淘汰
- TestMemoryPersistence (1): 跨实例 SQLite 持久化

### test_router_fallback.py — 路由回退（14 个测试）

- TestKeywordFallback (8): 单/多关键词匹配、多技能竞争、无匹配、全技能覆盖、rag/seo/support 匹配
- TestRouterFallback (6): LLM 异常/超时/空返回触发 fallback、LLM 正常不回退、无匹配 -> unknown、文件快捷路由

### test_router_fallback_edge.py — 路由边界（21 个测试）

- TestKeywordFallbackEdgeCases (14): 空串、纯空白、纯标点、纯英文、大小写混合、长文本关键词、多类别歧义、平局确定性、全关键词遍历、子串误报、换行符、特殊字符、4 万字符性能 < 0.1s
- TestRouterEdgeCases (7): LLM 返回 None、并发超时、空输入+LLM 失败、历史不影响 fallback、reflect_feedback 清除、文件快捷优先、多 tool_calls 保留

### test_cross_validate.py — 交叉验证（7 个测试）

- TestKeywordScores (3): 基础评分、单命中、无命中
- TestCrossValidation (4): LLM 与关键词一致、高置信覆盖、低置信保留、无冲突

### test_router_integration.py — 真实 LLM 集成（3 个测试，需 LM Studio）

- tool calling 能力验证、10 用例路由准确率(>=50%)、fallback 延迟 < 10ms
- pytest.mark.skipif：服务不可用时自动跳过

### test_scheduler.py — 定时调度（8 个测试）

初始化、启停、4 个注册任务（含每周业务价值报告与日志保留期清理）、状态结构、库存检查安全、日报安全、重复启动幂等、next_run_time

### test_tools.py — 关键词 + 工单工具（11 个测试）

- TestKeywordTool (4): 已知/未知关键词、淘宝热门、未知平台回退
- TestTicketTool (7): 创建、按订单查、未找到、按手机查、更新状态、无效更新、获取详情

### test_workflow.py — 工作流（6 个测试）

- TestSkillRegistry (3): router tools 注册、预期技能、runner 可调用
- TestAgentState (2): 必需字段、MAX_RETRIES
- TestReflectSkipSkills (1): file 和 rag 跳过 reflect

### test_ws_manager.py — WebSocket 管理（9 个测试）

初始化、启动前状态、空凭证不启动、未启动 stop 安全、状态结构、最大重启 5 次、冷却 30 秒、spawn 进程、terminate

### 测试方法总结

| 方法 | 使用文件 |
|------|---------|
| unittest.mock (patch/MagicMock) | test_integration, test_router_fallback, test_router_fallback_edge, test_cross_validate, test_scheduler, test_ws_manager |
| pytest fixture (conftest) | test_file_tool |
| pytest fixture (autouse) | test_router_integration |
| setup_method / teardown_method | test_memory, test_tools |
| tempfile 临时文件/数据库 | test_integration, test_tools, test_memory |
| pytest.mark.skipif | test_router_integration |
| 性能/延迟断言 | test_router_fallback_edge (< 0.1s), test_router_integration (< 10ms) |

---

## 17. CI/CD

GitHub Actions（.github/workflows/ci.yml）：

| Job | 内容 |
|-----|------|
| lint-and-test | flake8 语法检查（E9/F63/F7/F82 阻断）+ pytest 全量测试 |
| security-scan | bandit 安全扫描（medium 级别以上） |

- Python 3.11，pip 缓存
- 测试环境变量：mock LLM key + SQLite 测试数据库

---

## 18. 配置说明

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|---------|--------|------|
| LLM API Key | LLM_API_KEY / OPENAI_API_KEY | "" | 大语言模型密钥 |
| LLM API Base | LLM_API_BASE / OPENAI_API_BASE | https://dashscope.aliyuncs.com/compatible-mode/v1 | API 地址 |
| LLM Model | LLM_MODEL_NAME | deepseek-v4-pro | 模型名称 |
| LLM Temperature | LLM_TEMPERATURE | 0.3 | 生成温度 |
| LLM Max Tokens | LLM_MAX_TOKENS | 2000 | 最大输出 token |
| 本地 Embedding | USE_LOCAL_EMBEDDING | true | 是否使用本地嵌入模型 |
| 本地模型名 | LOCAL_EMBEDDING_MODEL | paraphrase-multilingual-MiniLM-L12-v2 | HuggingFace 模型 |
| 远程 Embedding | EMBEDDING_MODEL_NAME | text-embedding-v4 | DashScope 嵌入模型 |
| 飞书 App ID | FEISHU_APP_ID | "" | 飞书应用 ID |
| 飞书 App Secret | FEISHU_APP_SECRET | "" | 飞书应用密钥 |
| 飞书 Bot 名称 | FEISHU_BOT_NAME | Ecommerce Agent | 机器人名称 |
| Webhook Secret | FEISHU_WEBHOOK_SECRET | "" | 验证 Token |
| Encrypt Key | FEISHU_ENCRYPT_KEY | "" | AES 加密密钥 |
| 数据库 URL | DATABASE_URL | sqlite:///./feishu_agent.db | 数据库连接 |
| 日志级别 | LOG_LEVEL | INFO | 日志级别 |
| 服务端口 | APP_PORT | 8000 | HTTP 端口 |
| 混合检索权重 | HYBRID_ALPHA | 0.6 | 向量搜索权重（BM25 = 1-alpha） |
| 时间衰减系数 | TIME_DECAY_LAMBDA | 0.01 | RAG 时间衰减指数系数 |
| WS Worker 数 | WS_MAX_WORKERS | 3 | 飞书消息处理线程数 |
| Router LLM | ROUTER_API_KEY/BASE/MODEL_NAME | 复用 LLM_* | 路由专用模型（可指向更快模型） |
| VLM | VLM_API_KEY/BASE/MODEL_NAME | 复用 LLM_* | 多模态视觉模型 |
| LLM 供应商 | LLM_PROVIDER | 自动检测 | DashScope/OpenAI |
| API 鉴权 | API_KEY | "" | HTTP 接口 X-API-Key，**必填**；未配置时受保护端点默认拒绝（fail-closed） |
| 审批门 | APPROVAL_ENABLED | false | 高危操作（降价/打折等关键词触发）飞书审批开关。注意：定价技能的明示调价执行指令（update_price）无论本开关如何，始终强制走审批卡片确认后才执行 |
| 审批操作者白名单 | APPROVAL_OPERATORS | "" | 飞书 open_id 逗号分隔；启用审批门时必填，仅名单内用户可批准/拒绝/点选决策 |
| 每用户限流 | RATE_LIMIT_PER_MINUTE | 30 | 滑动窗口限流（次/分钟），/chat 与飞书入口生效，超限返回 429/提示 |
| 真实执行模式 | EXECUTOR_REAL_MODE | false | true 时执行器对接真实店铺平台（当前适配器为预留实现） |
| Thinking 模式 | LLM_ENABLE_THINKING | false | 是否开启 LLM 思考模式（默认关闭，输出经 strip_thinking 剥离） |
| 备用模型 | LLM_FALLBACK_MODEL | "" | 主模型连续失败时自动切换的备用模型名（不配置则不启用） |
| 备用模型密钥 | LLM_FALLBACK_API_KEY/BASE | 复用 LLM_* | 备用模型的 API 密钥和地址 |
| 路由缓存 | ROUTER_CACHE_ENABLED | true | temperature=0 路由结果缓存开关（TTL 600s, MAXSIZE 512） |
| 日志保留天数 | LOG_RETENTION_DAYS | 90 | token/业务任务日志保留期，每日 03:00 定时清理超期记录；<=0 关闭清理 |
| 回滚登记持久化 | ROLLBACK_PERSISTENCE_ENABLED | true | L4 待确认动作登记落库（pending_actions 表），重启后恢复未确认动作；测试环境自动关闭 |
| 关键词快速路径 | ROUTER_KEYWORD_FAST_PATH | true | 高置信关键词命中时跳过 LLM（conf>=2 唯一命中触发） |
| 定价指令快路径 | ROUTER_PRICING_DIRECTIVE_FAST_PATH | true | 明示调价指令（目标价/涨跌幅/折扣）经结构化判别直接路由 pricing_skill，审批门不依赖 LLM 能力；竞品语境/咨询句式/创作素材等歧义输入不触发 |
| LLM 请求超时 | LLM_REQUEST_TIMEOUT | 45 | 主 LLM 单次请求超时秒数 |
| LLM 最大重试 | LLM_MAX_RETRIES | 1 | 主 LLM 请求失败重试次数 |

---

## 19. License

MIT License
