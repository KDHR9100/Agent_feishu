# Ecommerce Agent 

基于 LangChain + FastAPI 构建的电商运营智能 Agent 服务，支持飞书消息接入、文件解析、库存预警、商品分析等功能。

## 1. 项目背景

在电商运营过程中，运营人员通常需要频繁完成商品销售数据分析、广告投放效果分析、运营内容生成、库存管理、竞品分析等任务。本项目构建了一个面向电商运营场景的智能 Agent，用户通过自然语言提出需求，Agent 自动判断任务类型，选择对应 Skill，并调用业务工具完成任务。

## 2. 项目流程

User (Feishu) -> FastAPI API层 -> Agent Router -> Skills层 -> Tools层 -> LLM分析决策

## 3. 核心技术栈

- **LangChain** - Agent编排、工具调用、RAG
- **LangGraph** - 状态机工作流管理
- **FastAPI + Uvicorn** - HTTP接口、服务化部署
- **SQLite + SQLAlchemy** - 数据存储、库存管理
- **pandas, openpyxl, xlrd** - Excel/CSV解析
- **PyPDF2, python-docx** - PDF/Word解析
- **APScheduler** - 定时监控、定时报告
- **FAISS** - RAG知识库
- **飞书Open API** - 消息接收、文件下载

## 4. 功能特性

### 4.1 文件解析与数据分析

支持CSV、Excel(.xlsx/.xls)、PDF、Word、飞书文档等多种格式。

使用示例：分析这个表格 message_id: xxx file_token: yyy file_name: sales_report.xlsx

### 4.2 库存预警系统

- **阈值配置** - 按商品类别设置不同预警阈值
- **预警等级划分** - critical(0库存)、high(低于30%)、medium(低于阈值)
- **定时监控** - 自动检测库存状态
- **飞书通知** - 通过飞书自动发送预警消息

### 4.3 商品分析、广告分析、运营内容生成

分析商品销售数据、广告投放效果、生成运营文案。

### 4.4 竞品分析、SEO优化、智能客服

监控竞品动态、关键词分析、客户问答等。

## 5. 项目结构

Agent_feishu/
├── app/
│   ├── agent/              # Agent核心模块
│   ├── agents/             # 专业化Agent（备用）
│   ├── api/                # API接口（飞书）
│   ├── skills/             # 业务技能模块
│   ├── tools/              # 工具模块
│   ├── rag/                # RAG知识库
│   ├── memory/             # 记忆模块
│   ├── monitoring/         # 监控统计
│   ├── models/             # 数据模型
│   ├── tasks/              # 定时任务
│   ├── utils/              # 工具函数
│   ├── config.py           # 配置管理
│   ├── prompts.py          # Prompt模板
│   └── main.py             # FastAPI入口
├── data/
│   └── vectorstore/        # 向量存储数据
├── scripts/
│   └── init_db.py          # 数据库初始化脚本
├── tests/                  # 测试用例
├── .env                    # 环境变量
├── requirements.txt        # 依赖列表
└── README.md

## 6. 快速开始

### 6.1 创建环境

conda create -n feishuagent python=3.11
conda activate feishuagent

### 6.2 安装依赖

pip install -r requirements.txt

### 6.3 配置环境变量

创建 .env 文件，参考项目规则。

### 6.4 初始化数据库

python scripts/init_db.py

### 6.5 启动服务

开发模式：uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
生产模式：uvicorn app.main:app --host 127.0.0.1 --port 8000

## 7. API接口

POST /chat - 聊天接口
POST /rag/query - RAG查询接口
GET /health - 健康检查
POST /feishu/webhook - 飞书Webhook

## 8. 飞书开放平台配置

1. 访问 https://open.feishu.cn/app 创建企业自建应用
2. 添加权限：doc:document:readonly, im:message:readonly, im:resource:readonly, im:message:send_as_bot
3. 配置事件订阅
4. 发布应用

## 9. 测试验证

python tests/test_llm_simple.py
python tests/test_inventory.py
pytest tests/ -v

## 10. 核心工作流

基于LangGraph的状态机工作流：
1. load_history - 加载会话历史
2. router - 意图识别与路由
3. skill_executor - 执行业务技能
4. answer - 生成最终回复
5. save_history - 保存会话历史

## 11. 配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| LLM_API_KEY | - | 大语言模型API密钥 |
| LLM_API_BASE | https://api.openai.com/v1 | API基础地址 |
| LLM_MODEL_NAME | gpt-4o-mini | 模型名称 |
| USE_LOCAL_EMBEDDING | true | 是否使用本地嵌入模型 |
| FEISHU_APP_ID | - | 飞书应用ID |
| DATABASE_URL | sqlite:///./feishu_agent.db | 数据库连接URL |
| APP_PORT | 8000 | 服务端口 |

## 12. License

MIT License
