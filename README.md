# Feishu E-commerce Agent

基于 LangChain + FastAPI 构建的电商运营智能 Agent 服务，支持飞书消息接入、文件解析、库存预警、竞品分析等功能。

## 1. 项目背景

在电商运营过程中，运营人员通常需要频繁完成商品销售数据分析、广告投放效果分析、营销内容生成、库存管理、竞品分析等任务。本项目构建了一个面向电商运营场景的智能 Agent，用户通过自然语言提出需求，Agent 自动判断任务类型，选择对应 Skill，并调用业务工具完成任务。

## 2. 项目架构

User (Feishu) -> FastAPI API层 -> Agent Router -> Skills层 -> Tools层 -> LLM分析报告

## 3. 核心技术栈

- LangChain - Agent编排、工具调用、RAG
- FastAPI + Uvicorn - HTTP接口、服务化部署
- SQLite + SQLAlchemy - 数据存储、库存管理
- pandas, openpyxl, xlrd - Excel/CSV解析
- PyPDF2, python-docx - PDF/Word解析
- APScheduler - 库存监控、定时报告
- FAISS - RAG知识库
- 飞书Open API - 消息接收、文件下载

## 4. 功能特性

### 4.1 文件解析与数据分析

支持CSV、Excel(.xlsx/.xls)、PDF、Word、飞书文档等多种格式。

使用示例：分析这个表格 message_id: xxx file_token: yyy file_name: sales_report.xlsx

### 4.2 库存预警系统

- 阈值配置 - 按商品类别设置不同预警阈值
- 紧急程度分级 - critical(0库存)、high(低于30%)、medium(低于阈值)
- 定时监控 - 自动检测库存状态
- 飞书通知 - 通过飞书自动发送预警消息

### 4.3 商品分析、广告分析、营销内容生成

分析商品销售数据、广告投放效果、生成营销文案。

### 4.4 竞品分析、SEO优化、智能客服

监控竞品动态、关键词分析、订单查询等。

## 5. 项目结构

```
Agent_feishu/
├── app/
│   ├── agent/              # Agent核心模块
│   ├── agents/             # 专业Agent
│   ├── api/                # API接口
│   ├── skills/             # 业务技能
│   ├── tools/              # 工具模块
│   ├── rag/                # RAG知识库
│   ├── memory/             # 记忆模块
│   ├── monitoring/         # 监控统计
│   ├── models/             # 数据模型
│   ├── tasks/              # 定时任务
│   ├── config.py           # 配置管理
│   ├── prompts.py          # Prompt模板
│   └── main.py             # FastAPI入口
├── data/                   # 数据目录
├── scripts/                # 脚本
├── tests/                  # 测试用例
├── .env                    # 环境变量
├── .env.example            # 环境变量示例
├── requirements.txt        # 依赖列表
└── README.md
```

## 6. 快速开始

### 6.1 创建环境

conda create -n feishuagent python=3.11
conda activate feishuagent

### 6.2 安装依赖

pip install -r requirements.txt

### 6.3 配置环境变量

cp .env.example .env

### 6.4 启动服务

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

## 7. API接口

- POST /chat - 聊天接口
- GET /health - 健康检查
- POST /feishu/webhook - 飞书Webhook

## 8. 飞书开放平台配置

1. 访问 https://open.feishu.cn/app 创建企业自建应用
2. 添加权限：docx:document:readonly, im:message:readonly, im:resource:readonly, im:message:send_as_bot
3. 配置事件订阅
4. 发布应用

## 9. 测试验证

python tests/test_llm_simple.py
python tests/test_inventory.py

## 10. License

MIT License
