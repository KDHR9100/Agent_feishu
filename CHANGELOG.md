# 更新日志 (CHANGELOG)

本项目所有重要变更均记录于此文档。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/)。

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