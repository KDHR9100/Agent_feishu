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
EVAL_SIM_MODEL=qwen3.8-flash
EVAL_JUDGE_API_BASE=...                                              # 裁判（建议与被测模型异源或至少异档）
EVAL_JUDGE_API_KEY=...
EVAL_JUDGE_MODEL=qwen3.8-max
EVAL_JUDGE_DISABLE_THINKING=true    # DashScope qwen3 系列：关思考模式，裁判单调用 73s→1.6s
# 被测 Agent 本体沿用主项目 .env 的 LLM_*/ROUTER_* 配置
```

可选调优：`EVAL_SIM_TIMEOUT`（默认 60s）/ `EVAL_JUDGE_TIMEOUT`（默认 240s，裁判 prompt 含完整轨迹，长于普通对话）。

```bash
# 单画像 smoke（约 50s，验证配置与读数）
python -m evaluation.cli run --persona ads_manager --max-turns 2 --eval-mode real

# 全量基线（13 画像 × 5 轮，约 30~40 分钟；产物在 evaluation/reports/run-*/）
python -m evaluation.cli run --persona all --max-turns 5 --eval-mode real
```

### 已知坑（实测）

- **DashScope qwen3 系列长输入默认开思考**：裁判单调用实测 73s（reasoning_tokens 占完成 98%），不开 `EVAL_JUDGE_DISABLE_THINKING` 时全量基线不可行。打分任务无需长思考，关掉后评分结论一致。
- **OpenAI 等严格校验未知参数的端点**保持思考开关为默认 `false`（`enable_thinking` 会被拒）。
- 每个画像一个 episode；攻击者画像（attacker）同样跑满，安全门由安全维一票否决。
- 运行产物目录（`evaluation/reports/run-*/`、`history/`）已被 gitignore，基线结论固化在 `docs/evaluation_plan.md` §10 与 CHANGELOG，不放轨迹原始数据。
- **全量真实基线已定稿**（run-20260910-132010，2026-09-10）：overall 0.5149、安全维 1.00、五维阈值按"基线 − 容差"回填 `configs/eval_config.yaml`——详见 `docs/evaluation_plan.md` §10.8（含缺陷档案与 M7b 修复闭环计划）。

## 常用命令

```bash
python -m evaluation.cli list-personas          # 列出 13 个画像
python -m evaluation.cli validate               # 校验画像 YAML + 配置
python -m evaluation.cli run --persona temu_operator --eval-mode mock
python -m pytest evaluation/tests -q            # 评测模块自身测试（56 个）
```

## 红线

- 不修改 `app/` 主代码任何一行；mock 模式完全不加载主项目
- 评测 workflow（`.github/workflows/eval.yml`）与主 CI 分离，失败不影响主流程
- 真实模式仅在手动触发（workflow_dispatch）时运行，需在 Secrets 配置凭据
