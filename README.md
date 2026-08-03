# Ecommerce Agent（电商金刚）

基于 LangGraph + FastAPI 构建的电商运营智能 Agent 服务，集成飞书 WebSocket 消息接入、RAG 混合检索知识库、文件解析、多轮对话记忆、Guardrails 安全防护等功能。用户通过飞书发送自然语言，Agent 自动识别意图、路由到对应技能、调用工具完成任务。

---

## 目录

1. [系统架构](#1-系统架构)
2. [LangGraph 工作流](#2-langgraph-工作流)
3. [路由机制](#3-路由机制)
4. [技能列表](#4-技能列表12-个)
5. [RAG 知识库系统](#5-rag-知识库系统)
6. [Guardrails 安全防护](#6-guardrails-安全防护)
7. [记忆系统](#7-记忆系统)
8. [飞书集成](#8-飞书集成)
9. [文件解析](#9-文件解析)
10. [定时任务](#10-定时任务)
11. [项目结构](#11-项目结构)
12. [快速开始](#12-快速开始)
13. [Docker 部署](#13-docker-部署)
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
    +- load_history    加载最近 5 条对话历史
    +- load_file       解析上传文件（若有）
    +- router          意图识别 + 技能路由（三层递进）
    +- skill_executor  执行 1~N 个技能（注册表模式，多技能 fan-out）
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
| 数据存储 | SQLite + SQLAlchemy | 商品销售、广告数据、对话历史 |
| 文件解析 | pandas, openpyxl, PyPDF2, python-docx | Excel/CSV/PDF/Word |
| 安全防护 | Guardrails + pycryptodome | 输入检测、飞书消息 AES 解密 |
| 定时任务 | APScheduler | 库存预警、日报生成 |
| 中文分词 | jieba | BM25 检索分词 |

---

## 2. LangGraph 工作流

### 节点定义（7 个节点）

| 节点 | 职责 |
|------|------|
| load_history | 从 LocalMemory 加载最近 5 条对话历史 |
| load_file | 若有文件路径，调用 file_parser_tool 解析文件 |
| router | 意图识别 + 技能路由，输出 skills_to_execute 列表（支持多技能） |
| skill_executor | 注册表模式迭代执行所有技能 |
| reflect | ReAct 反思：LLM 判断技能结果是否充分 |
| answer | 单结果直接提取；多结果调用 LLM 综合生成连贯回答 |
| save_history | 将用户输入和最终回答写入 LocalMemory |

### 条件边

- reflect_decision == "insufficient" -> 回到 router，携带 reflect_feedback 指导重新路由
- reflect_decision == "sufficient" -> 进入 answer
- 短路规则：file_analysis_skill 和 rag_skill 跳过 reflect 直接 sufficient
- 防死循环：retry_count >= MAX_RETRIES (2) 时强制 sufficient
- 容错：reflect LLM 超时 20 秒，异常时 fail-open 为 sufficient

### AgentState 定义（14 个字段）

user_input, conversation_id, history, tool_result, answer, intent, token_usage, file_path, file_content, skills_to_execute, skill_results, retry_count, reflect_feedback, reflect_decision

---

## 3. 路由机制

路由采用三层递进策略，确保高可用：

### 第一层：文件快捷路由

若 file_path 和 file_content 都存在，且用户输入为空/以 [文件] 开头/包含文件相关关键词（解析、分析、查看、解读等），直接路由到 file_analysis_skill，跳过 LLM 调用。

### 第二层：LLM Tool-Calling

将 12 个技能封装为 StructuredTool，通过 llm.bind_tools(tools) 让 LLM 以 function calling 方式选择技能。支持多技能选择。超时 20 秒。

### 第三层：交叉验证 + Keyword Fallback

- 交叉验证：LLM 选择后，用关键词评分验证。若关键词最高分技能与 LLM 不同且置信度 >= 2，则关键词结果优先。
- Keyword Fallback：LLM 调用超时或异常时，使用 KEYWORD_RULES 进行关键词匹配。
- 最终 Fallback：关键词也无匹配 -> intent = "unknown" -> LLM 闲聊兜底。
---

## 4. 技能列表（12 个）

| # | 技能名 | 功能 | 触发关键词 | 实现方式 |
|---|--------|------|-----------|---------|
| 1 | product_skill | 商品销售数据分析、趋势、利润率、SKU 对比 | 商品、销量、SKU、评价、卖得 | DB 查询 + 趋势/利润计算 + LLM 报告 |
| 2 | ads_skill | 广告投放效果、ROI/CTR/CPC、渠道对比 | 广告、投放、ROI、推广、花费、渠道 | DB 查询 + 指标计算 + 平台对比 + LLM |
| 3 | content_skill | 多平台营销文案（抖音/淘宝/小红书/微信/拼多多） | 文案、活动策划、营销、写一段 | 检测平台+模板 + LLM 生成 |
| 4 | inventory_skill | 库存预警、补货建议、周转分析 | 库存、补货、预警、周转、缺货 | DB 全量查询 + 按品类阈值检测 |
| 5 | competitor_skill | 竞品分析、市场竞争情报 | 竞品、竞争、对手、市场情报 | LLM 直接回答（截断 500 字符） |
| 6 | report_skill | 运营报告生成并保存为 Markdown | 报告、周报、月报、汇总 | LLM 总结 + file_tool 写入 reports/ |
| 7 | rag_skill | 知识库检索增强问答 | 规则、佣金、上架、平台规则、怎么算 | 混合检索 + LLM 生成 |
| 8 | seo_skill | SEO 优化、关键词研究、标题优化 | SEO、关键词、搜索量、标题优化、长尾词 | keyword_tool 查询 + LLM 分析 |
| 9 | support_skill | 客服：订单查询、退换货、物流、售后 | 订单、退款、退货、售后、客服、物流 | 意图分类 + ticket_tool + LLM |
| 10 | data_analysis_skill | 深度数据分析、趋势、异常检测 | 趋势、异常、同比、环比、统计 | DB 查询 + 基础统计 + LLM 专业分析 |
| 11 | file_analysis_skill | 文件解析分析报告 | 解析文件、分析文件、这个表格、这份数据 | 已解析 file_content + LLM 结构化报告 |
| 12 | help_skill | 使用帮助、功能介绍 | 帮助、你能做什么、功能、怎么用 | HELP_PROMPT + LLM |

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
- Routing 评估：8 个问题覆盖 8 个技能路由，测路由准确率 + 延迟
- Judge 评估：LLM 打分 1-5 分，三个维度（relevance / accuracy / completeness）

---

## 6. Guardrails 安全防护

纯关键词匹配，在飞书消息处理层（Agent 调用之前）拦截：

| 类型 | 关键词 | 动作 |
|------|--------|------|
| BLOCKED（拦截） | 政治、政府、反动、爆炸、杀人、毒品、武器、赌博、诈骗、盗版、黑客 | 直接返回拒绝消息 |
| REDIRECT（重定向） | 看病、医疗、股票、基金 | 返回引导消息 |
| ALLOW（放行） | 其他所有输入 | 正常进入 Agent 流程 |

---

## 7. 记忆系统

LocalMemory 双层存储架构：

| 层 | 实现 | 说明 |
|----|------|------|
| 内存层 | OrderedDict + LRU 淘汰 | 超过 1000 个会话时淘汰最久未用的 |
| 持久层 | SQLite（SQLAlchemy） | 表 Conversation，写入时同步，读取时懒加载 |

| 参数 | 值 |
|------|------|
| max_history | 10 条/会话 |
| max_conversations | 1000 |
| 工作流实际使用 | 最近 5 条 |
| DB 内容截断 | 4000 字符 |

每条消息格式：{"role": "user"/"assistant", "content": str, "timestamp": ISO时间}

---

## 8. 飞书集成

- 连接方式：lark-oapi SDK WebSocket 长连接（非 Webhook）
- 并发模型：消息队列 queue.Queue + ThreadPoolExecutor（默认 3 worker，WS_MAX_WORKERS 可调）
- 群聊策略：需 @bot 才响应；私聊直接处理
- 文件消息：检查扩展名（仅 .xlsx/.xls/.csv/.pdf/.docx）-> 下载到 data/uploads/ -> 解析
- 消息解密：AES 解密（pycryptodome）
- 进程管理：ws_manager 管理 WebSocket 子进程，最大重启 5 次，冷却 30 秒

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
---

## 11. 项目结构

```
Agent_feishu/
├── app/
│   ├── agent/                    # Agent 核心
│   │   ├── router.py             # 意图路由（LLM + 关键词 + 交叉验证 + fallback）
│   │   ├── workflow.py           # LangGraph 状态机（7 节点 + 条件边）
│   │   └── state.py              # AgentState 定义（14 字段, MAX_RETRIES=2）
│   ├── api/
│   │   └── feishu.py             # 飞书 Webhook + 签名验证 + AES 解密
│   ├── eval/
│   │   └── llm_judge.py          # LLM-as-Judge 评估
│   ├── memory/
│   │   └── local_memory.py       # 双层记忆（内存 LRU + SQLite 持久化）
│   ├── models/
│   │   ├── database.py           # SQLAlchemy 引擎
│   │   └── models.py             # ProductSale, AdsPerformance 数据模型
│   ├── monitoring/
│   │   └── stats.py              # 监控统计
│   ├── rag/
│   │   ├── vectorstore.py        # FAISS + 分块 + Embedding 三级降级
│   │   ├── hybrid_search.py      # BM25 + 向量 + RRF 融合 + CrossEncoder 精排
│   │   ├── retriever.py          # 检索 + LLM 生成
│   │   ├── doc_manager.py        # 文档 CRUD + SHA-256 变更检测 + 查询缓存
│   │   └── eval/
│   │       └── evaluate_rag.py   # 20 题关键词召回率评估
│   ├── skills/                   # 12 个业务技能
│   ├── tasks/
│   │   └── scheduler.py          # APScheduler 定时任务
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
│   ├── utils/
│   │   └── timeout.py            # 超时装饰器
│   ├── config.py                 # 配置管理（环境变量）
│   ├── prompts.py                # Prompt 模板
│   └── main.py                   # FastAPI 入口
├── data/
│   ├── documents/                # 知识库文档（.txt/.md）
│   ├── uploads/                  # 上传文件
│   └── vectorstore/              # FAISS 索引 + 哈希注册表 + 查询缓存
├── tests/                        # 12 个测试文件（详见第 16 节）
├── scripts/
│   └── init_db.py                # 数据库初始化
├── .github/workflows/
│   └── ci.yml                    # GitHub Actions CI
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example                  # 环境变量模板
├── .gitignore
├── requirements.txt
├── CHANGELOG.md
└── README.md
```

---

## 12. 快速开始

### 12.1 创建环境

```bash
conda create -n feishuagent python=3.11
conda activate feishuagent
```

### 12.2 安装依赖

```bash
pip install -r requirements.txt
```

### 12.3 配置环境变量

复制 .env.example 为 .env 并填写 LLM_API_KEY、FEISHU_APP_ID、FEISHU_APP_SECRET 等。

### 12.4 初始化数据库

```bash
python scripts/init_db.py
```

### 12.5 启动服务

```bash
# 开发模式
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 生产模式
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 12.6 RAG 评估（可选）

```bash
python -m app.rag.eval.evaluate_rag
```

---

## 13. Docker 部署

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
- 环境变量：env_file: .env
- 数据卷：./data:/app/data（知识库文档 + 向量索引）
- 模型缓存：model_cache 命名卷（持久化 HuggingFace 模型）
- 重启策略：unless-stopped

> 注意：首次启动需确保 HuggingFace 模型已缓存，否则 HF_HUB_OFFLINE=1 会导致降级到 DashScope 远程 Embedding。

---

## 14. API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | / | 服务状态 |
| GET | /health | 健康检查 |
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
| POST | /feishu/webhook | 飞书 Webhook |

---

## 15. 飞书开放平台配置

1. 访问 https://open.feishu.cn/app 创建企业自建应用
2. 添加权限：doc:document:readonly, im:message:readonly, im:resource:readonly, im:message:send_as_bot
3. 配置事件订阅：选择长连接模式，订阅 im.message.receive_v1
4. 设置 Encrypt Key 和 Verification Token
5. 发布应用
---

## 16. 单元测试

共 12 个测试文件，覆盖路由、工作流、记忆、安全、工具、调度等核心模块。

### 共享 Fixture（conftest.py）

| Fixture | 作用域 | 说明 |
|---------|--------|------|
| setup_test_database | session, autouse | 创建 product_sales / ads_performance 表 + 种子数据 |
| tmp_dir | function | 临时目录，测试后自动清理 |
| file_tool | function | 沙箱化 FileTool（基于 tmp_dir） |

### test_file_tool.py — 文件工具（13 个测试）

- TestPathTraversal (7): 正常路径允许、../../etc/passwd 读取拦截、路径穿越写入/删除/列目录/追加拦截
- TestFileOperations (6): 文本/JSON/CSV 格式写入读取、列目录、删除文件、追加内容

### test_guardrails.py — 安全护栏（5 个测试）

空输入允许、正常电商查询允许、危险关键词拦截（"制造爆炸" -> block）、非电商话题重定向（"股票走势" -> redirect）、批量电商查询允许

### test_integration.py — 多模块集成（18 个测试）

- TestFullWorkflowTextMessage (1): Mock LLM 执行完整 agent workflow
- TestSkillRegistryCompleteness (3): 12 个技能注册完整性、router tools 一致性
- TestGuardrailsIntegration (4): 安全/危险/离题/空输入批量验证
- TestMemoryPersistenceIntegration (3): 存取、会话隔离、max_history 裁剪
- TestRouterToolBinding (2): 12 个 tools 绑定、LLM tool_call 解析
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

初始化、启停、2 个注册任务、状态结构、库存检查安全、日报安全、重复启动幂等、next_run_time

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
| WS Worker 数 | WS_MAX_WORKERS | 3 | 飞书消息处理线程数 |

---

## 19. License

MIT License