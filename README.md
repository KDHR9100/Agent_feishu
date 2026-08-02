# Ecommerce Agent

基于 LangGraph + FastAPI 构建的电商运营智能 Agent 服务，集成飞书消息接入、RAG 知识库、文件解析、多轮对话记忆、Guardrails 安全防护等功能。

## 1. 项目背景

在电商运营过程中，运营人员需要频繁完成商品销售数据分析、广告投放效果分析、运营内容生成、库存管理、竞品分析等任务。本项目构建了一个面向电商运营场景的智能 Agent，用户通过飞书发送自然语言，Agent 自动判断意图、选择技能、调用工具完成任务，并支持多轮对话上下文记忆。

## 2. 系统架构

```
User (Feishu WebSocket) -> Guardrails -> Agent Router -> Skills -> Tools -> LLM
                                                          |
                                    RAG (FAISS + MMR + Cache)
                                    Memory (多轮对话历史)
```

### 核心工作流（LangGraph 状态机）

1. **load_history** - 加载会话历史（多轮记忆）
2. **router** - 意图识别与路由（含主题范围 Guardrails）
3. **skill_executor** - 执行业务技能（带历史上下文）
4. **answer** - 生成最终回复
5. **save_history** - 保存会话历史

## 3. 核心技术栈

| 类别 | 技术 | 说明 |
|------|------|------|
| Agent 编排 | LangGraph 0.2+ | 状态机工作流管理 |
| LLM 框架 | LangChain 0.2+ | 工具调用、消息处理 |
| LLM 模型 | deepseek-v4-pro | 通过 DashScope API 调用 |
| Web 框架 | FastAPI + Uvicorn | HTTP 接口、服务化部署 |
| 向量检索 | FAISS + MMR | 最大边际相关性检索 |
| Embedding | sentence-transformers | 本地多语言嵌入模型 |
| 文档管理 | SHA-256 + 增量更新 | 文档变更检测与向量库同步 |
| 飞书集成 | lark-oapi | WebSocket 长连接 |
| 数据存储 | SQLite + SQLAlchemy | 商品、库存、订单数据 |
| 文件解析 | pandas, openpyxl, PyPDF2 | Excel/CSV/PDF/Word |
| 安全防护 | Guardrails + AES | 输入检测、飞书消息解密 |

## 4. 功能特性

### 4.1 智能对话与多轮记忆

- 基于历史对话上下文进行多轮交互
- 自动加载和保存会话历史
- 支持文件内容跨轮次引用

### 4.2 RAG 知识库

- **文档管理** - 支持在 `data/documents/` 文件夹中添加/删除 `.txt`/`.md` 文档
- **变更检测** - 基于 SHA-256 哈希值自动检测文档增删改
- **增量更新** - 仅新增文档时增量添加向量，修改/删除时全量重建
- **MMR 检索** - 最大边际相关性检索，减少冗余结果，chunk_size=512, overlap=100
- **查询缓存** - 文档未变更时返回缓存结果，TTL=1 小时，自动失效
- **效果评估** - 内置 20 个电商场景测试问题，评估召回率和延迟

### 4.3 Guardrails 安全防护

- **输入检测** - 敏感词/违规内容过滤
- **主题限制** - 非电商问题礼貌拒绝并引导
- **输出脱敏** - 异常信息不暴露给用户

### 4.4 文件解析与数据分析

- 支持 CSV、Excel(.xlsx/.xls)、PDF、Word 格式
- 自动提取数据摘要统计（均值、最大值、最小值、标准差等）
- 结构化报告输出（标题、时间戳、分段、Emoji）

### 4.5 库存预警系统

- 按商品类别设置不同预警阈值
- 预警等级划分：critical / high / medium
- 定时监控与飞书通知

### 4.6 商品分析、广告分析、运营内容生成

分析商品销售数据、广告投放效果、生成运营文案。

## 5. 项目结构

```
Agent_feishu/
├── app/
│   ├── agent/                # Agent 核心
│   │   ├── router.py         # 意图路由（get_llm 单例 + Guardrails）
│   │   ├── workflow.py       # LangGraph 状态机工作流
│   │   └── state.py          # 状态定义
│   ├── api/                  # API 接口
│   │   └── feishu.py         # 飞书 Webhook + 签名验证 + AES 解密
│   ├── skills/               # 业务技能
│   │   ├── file_analysis_skill.py  # 文件分析（结构化报告）
│   │   ├── product_skill.py
│   │   ├── ads_skill.py
│   │   ├── content_skill.py
│   │   ├── inventory_skill.py
│   │   └── ...
│   ├── tools/                # 工具模块
│   │   ├── feishu_ws.py      # 飞书 WebSocket 长连接
│   │   ├── feishu_tool.py    # 飞书 API 封装
│   │   ├── file_parser_tool.py    # 文件解析 + format_file_summary
│   │   ├── guardrails.py     # 输入安全检测
│   │   ├── database_tool.py
│   │   └── file_tool.py
│   ├── rag/                  # RAG 知识库
│   │   ├── vectorstore.py    # FAISS + MMR + chunk 分块
│   │   ├── retriever.py      # 检索 + 生成
│   │   ├── doc_manager.py    # 文档管理 + 变更检测 + 查询缓存
│   │   └── eval/             # RAG 评估
│   │       └── evaluate_rag.py
│   ├── memory/               # 记忆模块
│   │   └── local_memory.py
│   ├── monitoring/           # 监控统计
│   │   └── stats.py
│   ├── models/               # 数据模型
│   ├── utils/                # 工具函数
│   ├── config.py             # 配置管理
│   ├── prompts.py            # Prompt 模板（含 Guardrails）
│   └── main.py               # FastAPI 入口
├── data/
│   ├── documents/            # 文档存储（.txt/.md）
│   │   ├── 佣金规则.txt
│   │   ├── 上架规则.txt
│   │   ├── 运营规则.txt
│   │   ├── 广告规则.txt
│   │   └── 平台规则.txt
│   └── vectorstore/          # 向量存储
│       ├── faiss_index/      # FAISS 索引
│       ├── doc_hashes.json   # 文档哈希注册表
│       └── query_cache.json  # 查询缓存
├── scripts/
│   └── init_db.py
├── .env                      # 环境变量
├── .env.example              # 环境变量示例
├── .gitignore
├── requirements.txt
└── README.md
```

## 6. 快速开始

### 6.1 创建环境

```bash
conda create -n feishuagent python=3.11
conda activate feishuagent
```

### 6.2 安装依赖

```bash
pip install -r requirements.txt
```

### 6.3 配置环境变量

创建 `.env` 文件，参考 `.env.example`：

```env
# LLM Configuration
LLM_API_KEY=your_api_key
LLM_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=deepseek-v4-pro

# Embedding
USE_LOCAL_EMBEDDING=true

# Feishu
FEISHU_APP_ID=your_app_id
FEISHU_APP_SECRET=your_app_secret
FEISHU_WEBHOOK_SECRET=your_webhook_secret
FEISHU_ENCRYPT_KEY=your_encrypt_key

# Database
DATABASE_URL=sqlite:///./feishu_agent.db

# Server
APP_PORT=8000
```

### 6.4 初始化数据库

```bash
python scripts/init_db.py
```

### 6.5 启动服务

```bash
# 开发模式
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 生产模式
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 6.6 Docker 部署

```bash
# 构建并启动（需要先创建 .env 文件）
docker compose up -d --build

# 查看日志
docker compose logs -f

# 停止服务
docker compose down
```



> 注意：Docker 部署需要预先配置好 .env 文件。模型缓存通过 named volume 持久化。

### 6.7 RAG 评估（可选）

```bash
python -m app.rag.eval.evaluate_rag
```

## 7. API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat` | 聊天接口 |
| POST | `/rag/query` | RAG 查询接口 |
| GET | `/health` | 健康检查 |
| POST | `/feishu/webhook` | 飞书 Webhook（含签名验证 + AES 解密） |
| GET | `/documents` | 列出文档 + 系统状态 |
| POST | `/documents` | 添加文档并自动同步向量库 |
| DELETE | `/documents/{name}` | 删除文档并自动同步向量库 |
| POST | `/rag/sync` | 手动同步向量库（`?force=true` 全量重建） |
| GET | `/rag/status` | RAG 系统状态 |

### 文档管理示例

```bash
# 添加文档
curl -X POST "http://localhost:8000/documents?name=new_rules.txt&content=文档内容"

# 删除文档
curl -X DELETE "http://localhost:8000/documents/old_rules.txt"

# 全量重建向量库
curl -X POST "http://localhost:8000/rag/sync?force=true"

# 查看系统状态
curl "http://localhost:8000/rag/status"
```

## 8. 飞书开放平台配置

1. 访问 https://open.feishu.cn/app 创建企业自建应用
2. 添加权限：`doc:document:readonly`, `im:message:readonly`, `im:resource:readonly`, `im:message:send_as_bot`
3. 配置事件订阅：选择长连接模式，订阅 `im.message.receive_v1`
4. 设置 Encrypt Key 和 Verification Token
5. 发布应用

## 9. RAG 系统设计

### 文档变更检测

```
扫描 data/documents/ → 计算 SHA-256 → 对比存储的哈希
                                    ↓
                    added → 增量更新（add_documents）
                    modified/deleted → 全量重建（rebuild FAISS）
                    no change → 跳过
```

### 查询缓存机制

```
查询请求 → 检查文档签名 → 签名匹配 → 返回缓存
                          ↓ 不匹配
                  向量检索 → 写入缓存 → 返回结果
```

缓存 key = `SHA256(query + doc_signature)`，文档变更时签名变化，缓存自动失效。

### MMR 检索

使用最大边际相关性（Max Marginal Relevance）检索：
- `chunk_size=512`, `chunk_overlap=100`
- `fetch_k=10`, `lambda_mult=0.5`
- 先检索 10 个候选，再从中选 3 个最相关且最少冗余的结果

### 评估结果

内置 20 个电商场景测试问题，覆盖佣金、上架、运营、营销 4 个类别：

```
Total questions: 20
Relevant results: 20/20 (100%)
Average recall: 78%
Average latency: 11ms
```

## 10. 配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| LLM_API_KEY | - | 大语言模型 API 密钥 |
| LLM_API_BASE | https://dashscope.aliyuncs.com/compatible-mode/v1 | API 地址 |
| LLM_MODEL_NAME | deepseek-v4-pro | 模型名称 |
| USE_LOCAL_EMBEDDING | true | 是否使用本地嵌入模型 |
| FEISHU_APP_ID | - | 飞书应用 ID |
| FEISHU_APP_SECRET | - | 飞书应用密钥 |
| FEISHU_BOT_NAME | Ecommerce Agent | 飞书机器人名称 |
| FEISHU_WEBHOOK_SECRET | - | Webhook 验证 Token |
| FEISHU_ENCRYPT_KEY | - | AES 加密密钥 |
| DATABASE_URL | sqlite:///./feishu_agent.db | 数据库连接 URL |
| APP_PORT | 8000 | 服务端口 |

## 11. License

MIT License
