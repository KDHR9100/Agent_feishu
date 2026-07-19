# 更新日志 (CHANGELOG)

本项目所有重要变更均记录于此文档。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/)。

---

## [Unreleased] - 智能化升级阶段

### 新增
- **LLM 智能路由**：基于 LangChain bind_tools 实现用户意图自动识别与 Skill 分发。
- **Function Calling**：结构化工具调用支持，覆盖商品分析、广告分析、内容生成、报告生成。
- **RAG 知识库**：基于 FAISS 向量存储与 OpenAI Embeddings 的文档检索增强生成。
- **多 Agent 协作**：Coordinator 统筹商品分析、广告分析、营销文案三位专家 Agent 分工协作。
- **对话记忆**：LocalMemory 管理对话历史，支持上下文理解与最近 5 条消息回溯。
- **报告生成 Skill**：支持自动汇总分析结果生成结构化报告。
- **数据库工具**：封装 SQLAlchemy 操作，支持商品销售与广告数据查询。
- **飞书 API 工具**：访问令牌获取、消息发送、文档创建等能力集成。
- **文件操作工具**：支持 JSON / CSV 等文件读写。

### 变更
- 工作流新增 load_history 与 save_history 节点，贯通对话记忆链路。
- AgentState 扩展 user_input、conversation_id、history、answer 等字段。
- 商品分析 Skill 整合数据库工具与 LLM，自动产出分析报告。

---

## 提交记录

### 2026-07-20 — 098ba89 全面智能化升级
**作者**: huajuanx

**变更范围**: 28 个文件，新增 1029 行

**主要内容**:
- 完善基础设施升级：LLM 路由、Function Calling、RAG 知识库、多 Agent 协作、对话记忆、报告生成等模块代码落地。
- 新增模块:
  - app/agent/ - 状态、路由、工作流
  - app/agents/ - 协调器、商品、广告、内容专家 Agent
  - app/memory/ - 对话记忆
  - app/rag/ - 向量存储与检索器
  - app/skills/ - 商品、广告、内容、报告 Skill
  - app/tools/ - 数据库、飞书 API、文件操作工具
  - app/config.py - 统一配置管理
  - app/prompts.py - 提示词模板集中管理

---

### 2026-07-19 — 749e45d 智能化升级基础
**作者**: huajuanx

**主要内容**:
- 初版智能化升级提交，引入 LLM 路由、Function Calling、RAG 知识库、多 Agent 协作、对话记忆等功能骨架。

---

### 2026-07-19 — 572db38 项目初始化
**作者**: KDHR9100

**主要内容**:
- Initial commit: Feishu Agent project
- 飞书电商智能助手项目首次提交，搭建基础 FastAPI 服务骨架与 /chat 接口。

---

## 版本约定

- feat: 新功能
- fix: Bug 修复
- refactor: 重构
- docs: 文档更新
- chore: 构建 / 杂项
