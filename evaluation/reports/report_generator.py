"""报告生成器：Markdown（CI 产物）+ HTML（本地复盘）。

- 总览表格 / 分维明细 / 失败 Top-N case（含完整 trajectory）；
- 与上次 run 对比（读取 ``{output}/history/*.jsonl`` 历史摘要）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import structlog

from evaluation.config import DIMENSIONS, EvalSettings
from evaluation.reports.metrics_aggregator import aggregate_by_persona

logger = structlog.get_logger(__name__)

#: 回答摘录长度（Markdown 明细用）
_MD_ANSWER_LIMIT = 400


def _fmt(value: Optional[float]) -> str:
    return "N/A" if value is None else f"{value:.4f}"


def _delta(current: Optional[float], previous: Optional[float]) -> str:
    if current is None or previous is None:
        return ""
    diff = current - previous
    sign = "+" if diff >= 0 else ""
    return f"（较上次 {sign}{diff:.4f}）"


def _failure_cases(
    episodes: List[dict], settings: EvalSettings, top_n: int
) -> List[dict]:
    """按画像加权分升序取最差 N 个 episode（全维 skipped 的不进失败榜）。"""

    by_persona = aggregate_by_persona(episodes, settings)
    candidates = [
        ep for ep in episodes
        if by_persona.get(str(ep.get("persona_id")), {}).get("weighted_score") is not None
    ]
    ranked = sorted(
        candidates,
        key=lambda ep: by_persona.get(str(ep.get("persona_id")), {}).get("weighted_score", 1.0),
    )
    return ranked[:top_n]


def _render_episode_md(episode: dict) -> str:
    lines: List[str] = []
    lines.append(f"### {episode.get('persona_id')}（{episode.get('persona_name', '')}）")
    lines.append(f"- 目标: {episode.get('goal', '')}")
    term = episode.get("termination") or {}
    lines.append(f"- 终止: {term.get('reason')} @ {term.get('turns_used')} 轮")
    if episode.get("error"):
        lines.append(f"- **运行错误**: {episode['error']}")
    scores = episode.get("scores", {}) or {}
    for dim in DIMENSIONS:
        s = scores.get(dim)
        if s is None:
            continue
        flag = "SKIP" if s.get("skipped") else ("PASS" if s.get("passed") else "FAIL")
        lines.append(
            f"- [{flag}] {dim}: {float(s['score']):.2f} — {s.get('reason', '')}"
        )
        for ev in (s.get("evidence") or [])[:3]:
            lines.append(f"  - 证据: {str(ev)[:200]}")
    lines.append("")
    lines.append("<details><summary>完整 trajectory</summary>")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(episode, ensure_ascii=False, indent=2)[:8000])
    lines.append("```")
    lines.append("")
    lines.append("</details>")
    return "\n".join(lines)


def render_markdown(
    run_id: str,
    episodes: List[dict],
    metrics: dict,
    settings: EvalSettings,
    previous: Optional[dict],
) -> str:
    """生成 Markdown 报告。"""

    mode = episodes[0].get("mode", "unknown") if episodes else "unknown"
    lines: List[str] = []
    lines.append(f"# 合成用户评测报告 · {run_id}")
    lines.append("")
    if mode == "mock":
        lines.append("> **MODE=mock — 仅管路验证，分数无质量含义**")
        lines.append("")
    lines.append(f"- 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 模式: {mode}")
    lines.append(f"- Episode 数: {metrics.get('episode_count')}")
    lines.append(
        f"- **总分: {_fmt(metrics.get('overall'))}**（门禁 {settings.overall_gate}）"
        f" → {'PASS' if metrics.get('passed') else 'FAIL'}"
    )
    if metrics.get("safety_gate_tripped"):
        lines.append("- **安全一票否决已触发**")
    if metrics.get("error_episodes"):
        lines.append(f"- 运行错误 episode: {metrics['error_episodes']}")
    lines.append("")

    # ---- 与上次 run 对比 ----
    if previous:
        lines.append("## 与上次 run 对比")
        lines.append("")
        lines.append(f"- 基线: {previous.get('run_id')} @ {previous.get('timestamp')}")
        lines.append(
            f"- 总分: {_fmt(metrics.get('overall'))}"
            f"{_delta(metrics.get('overall'), previous.get('overall'))}"
        )
        lines.append("")
        lines.append("| 维度 | 本次 | 上次 | Δ |")
        lines.append("|---|---|---|---|")
        prev_dims = previous.get("by_dimension", {}) or {}
        for dim in DIMENSIONS:
            cur = (metrics.get("by_dimension", {}) or {}).get(dim, {}).get("score")
            prv = prev_dims.get(dim)
            if isinstance(prv, dict):  # 兼容两种历史摘要形态
                prv = prv.get("score")
            diff = "" if (cur is None or prv is None) else f"{cur - prv:+.4f}"
            lines.append(f"| {dim} | {_fmt(cur)} | {_fmt(prv)} | {diff} |")
        lines.append("")

    # ---- 总览表 ----
    lines.append("## 五维总览")
    lines.append("")
    lines.append("| 维度 | 得分 | 阈值 | 结果 | 失败画像 |")
    lines.append("|---|---|---|---|---|")
    for dim in DIMENSIONS:
        d = (metrics.get("by_dimension", {}) or {}).get(dim, {})
        failed = ", ".join(d.get("failed_personas", [])) or "-"
        lines.append(
            f"| {dim} | {_fmt(d.get('score'))} | {d.get('threshold')} | "
            f"{'PASS' if d.get('passed') else 'FAIL'} | {failed} |"
        )
    lines.append("")

    # ---- 按画像 ----
    lines.append("## 按画像")
    lines.append("")
    lines.append("| 画像 | 加权分 | 轮次 | 终止 | 结果 |")
    lines.append("|---|---|---|---|---|")
    for pid, info in (metrics.get("by_persona", {}) or {}).items():
        lines.append(
            f"| {pid} | {_fmt(info.get('weighted_score'))} | {info.get('turns_used')} | "
            f"{info.get('termination')} | {'PASS' if info.get('passed') else 'FAIL'} |"
        )
    lines.append("")

    # ---- 按轮次 ----
    lines.append("## 按轮次")
    lines.append("")
    lines.append("| 轮次 | 到达 episode 数 | 工具调用正确率 |")
    lines.append("|---|---|---|")
    for turn, info in (metrics.get("by_turn", {}) or {}).items():
        lines.append(f"| {turn} | {info.get('episodes')} | {info.get('tool_correct_rate')} |")
    lines.append("")

    # ---- 失败 Top-N ----
    failures = _failure_cases(episodes, settings, settings.top_failures)
    if failures:
        lines.append(f"## 失败 Top{len(failures)} 详情")
        lines.append("")
        for ep in failures:
            lines.append(_render_episode_md(ep))
            lines.append("")

    return "\n".join(lines) + "\n"


_HTML_STYLE = """
body{font-family:-apple-system,'Segoe UI',Roboto,'PingFang SC',sans-serif;margin:24px;
     color:#1f2328;background:#fff;max-width:1080px}
table{border-collapse:collapse;margin:12px 0;width:100%}
th,td{border:1px solid #d0d7de;padding:6px 10px;text-align:left;font-size:14px}
th{background:#f6f8fa}
.pass{color:#1a7f37;font-weight:600}.fail{color:#cf222e;font-weight:600}
.warn{background:#fff8c5;padding:10px 14px;border:1px solid #d4a72c;border-radius:6px}
details{margin:8px 0}summary{cursor:pointer;font-weight:600;color:#0969da}
pre{background:#f6f8fa;padding:10px;overflow:auto;font-size:12px;border-radius:6px}
h2{border-bottom:1px solid #d0d7de;padding-bottom:6px}
"""


def render_html(
    run_id: str,
    episodes: List[dict],
    metrics: dict,
    settings: EvalSettings,
    previous: Optional[dict],
) -> str:
    """生成自包含 HTML 报告（内嵌数据，无外部依赖）。"""

    mode = episodes[0].get("mode", "unknown") if episodes else "unknown"
    md_like_rows: List[str] = []
    for dim in DIMENSIONS:
        d = (metrics.get("by_dimension", {}) or {}).get(dim, {})
        cls = "pass" if d.get("passed") else "fail"
        state = "SKIP" if d.get("score") is None else ("PASS" if d.get("passed") else "FAIL")
        md_like_rows.append(
            f"<tr><td>{dim}</td><td>{_fmt(d.get('score'))}</td><td>{d.get('threshold')}</td>"
            f"<td class='{cls}'>{state}</td><td>{', '.join(d.get('failed_personas', [])) or '-'}</td></tr>"
        )

    persona_rows: List[str] = []
    for pid, info in (metrics.get("by_persona", {}) or {}).items():
        cls = "pass" if info.get("passed") else "fail"
        persona_rows.append(
            f"<tr><td>{pid}</td><td>{_fmt(info.get('weighted_score'))}</td>"
            f"<td>{info.get('turns_used')}</td><td>{info.get('termination')}</td>"
            f"<td class='{cls}'>{'PASS' if info.get('passed') else 'FAIL'}</td></tr>"
        )

    case_blocks: List[str] = []
    for ep in _failure_cases(episodes, settings, settings.top_failures):
        case_blocks.append(
            "<details><summary>{}（加权分 {}）</summary><pre>{}</pre></details>".format(
                ep.get("persona_id"),
                _fmt((metrics.get("by_persona", {}) or {}).get(str(ep.get("persona_id")), {}).get("weighted_score")),
                json.dumps(ep, ensure_ascii=False, indent=2)[:16000].replace("<", "&lt;"),
            )
        )

    warn = ""
    if mode == "mock":
        warn = '<div class="warn"><strong>MODE=mock</strong> — 仅管路验证，分数无质量含义</div>'
    prev_block = ""
    if previous:
        prev_block = (
            f"<p>基线: {previous.get('run_id')} @ {previous.get('timestamp')} — "
            f"上次总分 {_fmt(previous.get('overall'))}"
            f"{_delta(metrics.get('overall'), previous.get('overall'))}</p>"
        )

    overall_cls = "pass" if metrics.get("passed") else "fail"
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>评测报告 {run_id}</title><style>{_HTML_STYLE}</style></head>
<body>
<h1>合成用户评测报告 · {run_id}</h1>
{warn}
<p>模式: {mode} | Episode 数: {metrics.get('episode_count')}</p>
<h2>总分: <span class="{overall_cls}">{_fmt(metrics.get('overall'))}</span>
（门禁 {settings.overall_gate}）</h2>
{prev_block}
<h2>五维总览</h2>
<table><tr><th>维度</th><th>得分</th><th>阈值</th><th>结果</th><th>失败画像</th></tr>
{''.join(md_like_rows)}</table>
<h2>按画像</h2>
<table><tr><th>画像</th><th>加权分</th><th>轮次</th><th>终止</th><th>结果</th></tr>
{''.join(persona_rows)}</table>
<h2>失败 Top{settings.top_failures}（含完整 trajectory）</h2>
{''.join(case_blocks) or '<p>无失败 case</p>'}
<script type="application/json" id="eval-data">{json.dumps({'metrics': metrics}, ensure_ascii=False)[:20000]}</script>
</body></html>
"""


def save_history(
    history_dir: Path,
    run_id: str,
    metrics: dict,
    episodes: List[dict],
) -> Path:
    """落盘历史摘要 JSONL（下次 run 的对比基线）。"""

    history_dir.mkdir(parents=True, exist_ok=True)
    path = history_dir / f"{run_id}.jsonl"
    summary = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "overall": metrics.get("overall"),
        "passed": metrics.get("passed"),
        "by_dimension": {
            d: v.get("score") for d, v in (metrics.get("by_dimension", {}) or {}).items()
        },
        "episodes": [
            {
                "persona_id": ep.get("persona_id"),
                "weighted": (metrics.get("by_persona", {}) or {})
                .get(str(ep.get("persona_id")), {})
                .get("weighted_score"),
            }
            for ep in episodes
        ],
    }
    path.write_text(json.dumps(summary, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_previous_run(
    history_dir: Path,
    exclude_run_id: str,
) -> Optional[dict]:
    """读取最近一次（除当前 run 外）的历史摘要。"""

    if not history_dir.exists():
        return None
    candidates = sorted(p for p in history_dir.glob("*.jsonl") if p.stem != exclude_run_id)
    if not candidates:
        return None
    try:
        data = json.loads(candidates[-1].read_text(encoding="utf-8").strip())
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        logger.warning("history_corrupt", file=str(candidates[-1]))
        return None


def generate_reports(
    run_id: str,
    episodes: List[dict],
    metrics: dict,
    settings: EvalSettings,
    output_dir: Path,
) -> Dict[str, Path]:
    """生成全部产物：report.md / report.html / history。"""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    history_dir = output_dir / "history"

    previous = load_previous_run(history_dir, run_id)
    md = render_markdown(run_id, episodes, metrics, settings, previous)
    html = render_html(run_id, episodes, metrics, settings, previous)

    md_path = output_dir / "report.md"
    html_path = output_dir / "report.html"
    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")
    save_history(history_dir, run_id, metrics, episodes)

    logger.info("reports_generated", md=str(md_path), html=str(html_path))
    return {"markdown": md_path, "html": html_path}
