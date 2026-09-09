# 合成用户评测系统（evaluation/）

用 LLM 模拟真实运营人员与 FeishuAgent 多轮对话，从任务完成 / 多轮一致性 / 工具调用 / 幻觉 / 安全五个维度自动打分，产出 Markdown + HTML 报告，挂 GitHub Actions 做回归。方案文档：`docs/evaluation_plan.md`（含实现记录）。

## 5 分钟上手

```bash
# 1. 安装评测依赖（独立于主 requirements.txt，不污染主环境）
pip install -e ".[eval]"

# 2. mock 模式跑通全量画像（零 token，<1s）
EVAL_MODE=mock python -m evaluation.cli run --persona all --output evaluation/reports

# 3. 查看产物
ls evaluation/reports/run-*/        # report.md / report.html / metrics.json / trajectory.jsonl
```

## 真实模式（需要 LLM）

在 `.env` 追加（或 export），支持任意 OpenAI 兼容端点（含本地 vLLM）：

```bash
EVAL_MODE=real
EVAL_SIM_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1   # 模拟用户
EVAL_SIM_API_KEY=sk-xxx
EVAL_SIM_MODEL=qwen3.6-flash
EVAL_JUDGE_API_BASE=...                                              # 裁判（建议与被测模型异源）
EVAL_JUDGE_API_KEY=...
EVAL_JUDGE_MODEL=...
# 被测 Agent 本体沿用主项目 .env 的 LLM_*/ROUTER_* 配置
python -m evaluation.cli run --persona ads_manager --max-turns 2 --eval-mode real
```

## 常用命令

```bash
python -m evaluation.cli list-personas          # 列出 13 个画像
python -m evaluation.cli validate               # 校验画像 YAML + 配置
python -m evaluation.cli run --persona temu_operator --eval-mode mock
python -m pytest evaluation/tests -q            # 评测模块自身测试（46 个）
```

## 红线

- 不修改 `app/` 主代码任何一行；mock 模式完全不加载主项目
- 评测 workflow（`.github/workflows/eval.yml`）与主 CI 分离，失败不影响主流程
- 真实模式仅在手动触发（workflow_dispatch）时运行，需在 Secrets 配置凭据
