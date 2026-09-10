"""多轮一致性评测器：第 N 轮后是否还记得前面信息（规则 + LLM 混合）。

- 规则层：探针命中检查 + 兜底话术检查（"请提供/不知道您指"类失忆信号）；
- LLM 层（real）：裁判只判"矛盾"，与规则层取 min，只降不升。
"""

from __future__ import annotations

from typing import List, Tuple

import structlog

from evaluation.evaluators.base import BaseEvaluator, EvalResult, load_prompt, parse_json_loose
from evaluation.evaluators.task_completion import _render_conversation
from evaluation.personas.base_persona import BasePersona

logger = structlog.get_logger(__name__)

#: 失忆兜底话术模式（出现即视为"不记得"）
FALLBACK_PHRASES = (
    "请提供", "请告诉我", "请明确", "无法查询", "不知道您指",
    "没有找到相关", "没有相关记录", "哪个 SKU", "请补充",
)


class MultiTurnConsistencyEvaluator(BaseEvaluator):
    name = "multi_turn_consistency"

    def evaluate(self, trajectory: dict, persona: BasePersona) -> EvalResult:
        turns = trajectory.get("turns", [])
        probes = persona.consistency_probes
        if not probes:
            return EvalResult(score=1.0, passed=True, skipped=True, reason="画像未声明一致性探针")
        if not turns:
            return EvalResult(score=0.0, passed=False, skipped=True, reason="无有效轮次")

        passed_probes, failed_probes = self._rule_layer(turns, probes)

        if not failed_probes:
            return EvalResult(
                score=1.0, passed=True,
                reason=f"{len(passed_probes)}/{len(probes)} 探针全部命中",
                evidence=passed_probes,
            )

        # real 模式：裁判复核失败探针，避免表述差异造成的误判
        judge_score = self._judge_layer(trajectory, passed_probes, failed_probes)
        rule_score = len(passed_probes) / len(probes)
        score = min(rule_score, judge_score) if judge_score is not None else rule_score
        return EvalResult(
            score=round(score, 4),
            passed=self._passed(score),
            reason=f"探针失败 {len(failed_probes)}/{len(probes)}",
            evidence=(passed_probes + failed_probes)[:8],
        )

    # ---- 规则层 ----
    def _rule_layer(
        self, turns: List[dict], probes: list
    ) -> Tuple[List[str], List[str]]:
        passed: List[str] = []
        failed: List[str] = []
        for probe in probes:
            idx = probe.at_turn - 1
            if idx >= len(turns):
                failed.append(f"turn {probe.at_turn}: 探针轮不存在（对话提前结束）")
                continue
            answer = str(turns[idx].get("agent_answer", ""))
            hit = probe.expect_reference in answer
            amnesia = any(p in answer for p in FALLBACK_PHRASES)
            if hit and not amnesia:
                passed.append(f"turn {probe.at_turn}: 命中引用「{probe.expect_reference}」")
            else:
                why = "失忆兜底话术" if amnesia else f"未包含「{probe.expect_reference}」"
                failed.append(
                    f"turn {probe.at_turn}: {why} | 回答片段: {answer[:120]}"
                )
        return passed, failed

    # ---- LLM 层（real，可选）----
    def _judge_layer(
        self, trajectory: dict, passed: List[str], failed: List[str]
    ) -> float | None:
        if self.judge is None:
            return None
        rule_findings = "通过:\n" + "\n".join(passed or ["无"]) + "\n失败:\n" + "\n".join(failed)
        prompt = load_prompt("multi_turn_consistency.md").format(
            rule_findings=rule_findings,
            conversation=_render_conversation(trajectory),
        )
        try:
            raw = self.judge.invoke(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("consistency_judge_failed", error=str(exc))
            return None
        parsed = parse_json_loose(raw)
        if parsed is None:
            return None
        contradiction_turns = parsed.get("contradiction_turns", [])
        n_turns = max(len(trajectory.get("turns", [])), 1)
        # 矛盾轮占比 → 一致性分（只降不升，与规则层取 min）
        return 1.0 - min(1.0, len(contradiction_turns) / max(n_turns, 1))
