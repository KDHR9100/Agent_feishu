# -*- coding: utf-8 -*-
"""探针评测报告聚合工具

把 intent_probe 产出的 JSONL 结果聚合成可读的 Markdown 报告:
分阶段通过率 / 路由准确率 / LLM 评审均分 / token 成本 / 失败聚类,
多次跑批输入时自动生成基线对比表。

用法:
  python3 scripts/eval_report.py                          # 聚合 data/reports/ 全部探针 JSONL
  python3 scripts/eval_report.py file1.jsonl file2.jsonl  # 指定文件
  python3 scripts/eval_report.py --out report.md          # 指定输出路径
"""
import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

DEFAULT_GLOB = "data/reports/intent_probe_*.jsonl"

# 探针内部 phase=chat 的即 text 阶段用例, 展示时归一命名
PHASE_LABEL = {"chat": "text"}


def load_records(path):
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def summarize(records):
    total = len(records)
    passed = sum(1 for r in records if r.get("passed"))
    judged = [r for r in records if isinstance(r.get("judge_score"), (int, float))]
    judge_avg = (
        round(sum(r["judge_score"] for r in judged) / len(judged), 2) if judged else None
    )
    routed = [r for r in records if isinstance(r.get("route_ok"), bool)]
    route_acc = (
        round(sum(1 for r in routed if r["route_ok"]) / len(routed) * 100, 1)
        if routed else None
    )
    tokens = sum(
        (r.get("token_usage") or {}).get("total_tokens", 0) for r in records
    )
    elapsed = [r.get("elapsed") for r in records if isinstance(r.get("elapsed"), (int, float))]
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total * 100, 1) if total else 0.0,
        "judge_avg": judge_avg,
        "judge_n": len(judged),
        "route_acc": route_acc,
        "tokens": tokens,
        "avg_elapsed": round(sum(elapsed) / len(elapsed), 1) if elapsed else None,
    }


def phase_table(records):
    by_phase = defaultdict(list)
    for r in records:
        by_phase[PHASE_LABEL.get(r.get("phase", "?"), r.get("phase", "?"))].append(r)
    lines = [
        "| 阶段 | 场景 | PASS | FAIL | 通过率 | 评审均分 |",
        "|---|---|---|---|---|---|",
    ]
    for phase in sorted(by_phase):
        s = summarize(by_phase[phase])
        judge = "%.2f (n=%d)" % (s["judge_avg"], s["judge_n"]) if s["judge_avg"] else "-"
        lines.append(
            "| %s | %d | %d | %d | %.1f%% | %s |"
            % (phase, s["total"], s["passed"], s["failed"], s["pass_rate"], judge)
        )
    return "\n".join(lines), by_phase


def failure_table(records):
    fails = [r for r in records if not r.get("passed")]
    if not fails:
        return "本轮无失败用例。", []
    lines = ["| 用例 | 阶段 | 路由 | 评审 | 失败原因 |", "|---|---|---|---|---|"]
    reasons = []
    for r in sorted(fails, key=lambda x: x.get("sid", "")):
        reason = str(r.get("reason") or r.get("judge_reason") or "")[:60].replace("|", "/")
        lines.append(
            "| %s | %s | %s | %s | %s |"
            % (r.get("sid", "?"), PHASE_LABEL.get(r.get("phase"), r.get("phase")),
               r.get("intent", "-"), r.get("judge_score", "-"), reason)
        )
        reasons.append(r)
    return "\n".join(lines), reasons


def build_report(paths):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = ["# 探针评测报告", "", "> 生成时间: %s | 数据源: %d 个结果文件" % (now, len(paths)), ""]
    all_summaries = []
    for path in paths:
        records = load_records(path)
        if not records:
            continue
        s = summarize(records)
        all_summaries.append((os.path.basename(path), s, records))

    # 基线对比
    if len(all_summaries) > 1:
        lines += ["## 多轮基线对比", "",
                  "| 结果文件 | 场景 | PASS | 通过率 | 评审均分 | 路由准确率 | state内token |",
                  "|---|---|---|---|---|---|---|"]
        for name, s, _ in all_summaries:
            judge = "%.2f" % s["judge_avg"] if s["judge_avg"] else "-"
            route = "%.1f%%" % s["route_acc"] if s["route_acc"] is not None else "-"
            lines.append("| %s | %d | %d | %.1f%% | %s | %s | %s |"
                         % (name, s["total"], s["passed"], s["pass_rate"],
                            judge, route, "{:,}".format(s["tokens"])))
        lines.append("")

    # 每个文件的明细 (通常只有一轮; 多轮时各自成节)
    for name, s, records in all_summaries:
        lines += [
            "## %s" % name, "",
            "- 场景数: **%d** | PASS: **%d** | FAIL: **%d** | 通过率: **%.1f%%**"
            % (s["total"], s["passed"], s["failed"], s["pass_rate"]),
        ]
        if s["judge_avg"]:
            lines.append("- LLM 评审均分: **%.2f/5** (n=%d)" % (s["judge_avg"], s["judge_n"]))
        if s["route_acc"] is not None:
            lines.append("- 路由准确率: **%.1f%%**" % s["route_acc"])
        if s["avg_elapsed"]:
            lines.append("- 平均单场景耗时: %.1fs | /chat 响应内 token 合计: %s"
                         % (s["avg_elapsed"], "{:,}".format(s["tokens"])))
        lines.append("")
        pt, by_phase = phase_table(records)
        lines += ["### 分阶段结果", "", pt, ""]
        ft, reasons = failure_table(records)
        lines += ["### 失败清单 (%d)" % len(reasons), "", ft, ""]
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="探针 JSONL -> Markdown 评测报告")
    parser.add_argument("files", nargs="*", help="探针 JSONL 路径 (缺省聚合全部)")
    parser.add_argument("--out", default=None, help="输出 Markdown 路径")
    args = parser.parse_args()

    paths = args.files or sorted(glob.glob(DEFAULT_GLOB))
    if not paths:
        print("未找到探针结果文件 (%s)" % DEFAULT_GLOB)
        sys.exit(1)

    report = build_report(paths)
    out_path = args.out or os.path.join(
        "data/reports", "eval_report_%s.md" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print("报告已保存: %s" % out_path)


if __name__ == "__main__":
    main()
