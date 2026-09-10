"""任务完成度评测器：goal 是否被满足。

- mock / 无裁判：规则层——success_criteria 关键词在全部回答中的命中率；
- real：LLM-as-Judge（prompts/task_completion.md），区分"建议"与"动作"。
"""

from __future__ import annotations

from typing import List

import structlog

from evaluation.evaluators.base import BaseEvaluator, EvalResult, load_prompt, parse_json_loose
from evaluation.personas.base_persona import BasePersona

logger = structlog.get_logger(__name__)


def _render_conversation(trajectory: dict) -> str:
    lines: List[str] = []
    for turn in trajectory.get("turns", []):
        lines.append(f"turn {turn.get('turn')}")
        lines.append(f"用户: {turn.get('user_message', '')}")
        lines.append(f"助手: {str(turn.get('agent_answer', ''))[:800]}")
    return "\n".join(lines) or "（无对话）"


class TaskCompletionEvaluator(BaseEvaluator):
    name = "task_completion"

    def evaluate(self, trajectory: dict, persona: BasePersona) -> EvalResult:
        turns = trajectory.get("turns", [])
        termination = (trajectory.get("termination") or {}).get("reason", "")

        if persona.is_adversarial or termination == "safety_abort":
            return EvalResult(
                score=1.0, passed=True, skipped=True,
                reason="对抗/安全中止 episode 不评任务完成度",
            )
        if not turns:
            return EvalResult(
                score=0.0, passed=False, skipped=True,
                reason="无有效轮次，无法评任务完成度",
            )
        if self.judge is not None:
            return self._judge_evaluate(trajectory, persona, termination)
        return self._rule_evaluate(trajectory, persona)

    # ---- 规则层（mock / 零成本）----
    def _rule_evaluate(self, trajectory: dict, persona: BasePersona) -> EvalResult:
        corpus = "\n".join(str(t.get("agent_answer", "")) for t in trajectory.get("turns", []))
        missing = [c for c in persona.success_criteria if c not in corpus]
        score = 1.0 - len(missing) / max(len(persona.success_criteria), 1)
        evidence = [
            f"criteria 命中: {c}" for c in persona.success_criteria if c in corpus
        ][:5]
        reason = "全部验收标准命中" if not missing else f"未命中验收标准: {missing}"
        return EvalResult(score=round(score, 4), passed=self._passed(score), reason=reason, evidence=evidence)

    # ---- LLM-as-Judge（real）----
    def _judge_evaluate(self, trajectory: dict, persona: BasePersona, termination: str) -> EvalResult:
        prompt = load_prompt("task_completion.md").format(
            goal=persona.goal,
            criteria="\n".join(f"- {c}" for c in persona.success_criteria) or "-（未声明）",
            conversation=_render_conversation(trajectory),
            termination=termination or "finished_keyword",
        )
        try:
            raw = self.judge.invoke(prompt)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001 - 裁判故障降级到规则层
            logger.warning("task_completion_judge_failed", error=str(exc))
            result = self._rule_evaluate(trajectory, persona)
            result.reason = f"judge_failed, 降级规则层: {result.reason}"
            return result

        parsed = parse_json_loose(raw)
        if parsed is None or "score" not in parsed:
            result = self._rule_evaluate(trajectory, persona)
            result.reason = f"judge 输出不可解析, 降级规则层: {result.reason}"
            return result

        score = float(parsed.get("score", 0.0))
        if score < 0:  # 约定: -1 表示 skipped
            return EvalResult(score=1.0, passed=True, skipped=True, reason=str(parsed.get("reason", "judge 判定不适用")))
        score = max(0.0, min(1.0, score))
        evidence = [str(e) for e in parsed.get("evidence", [])][:8]
        return EvalResult(
            score=score,
            passed=self._passed(score),
            reason=str(parsed.get("reason", "")),
            evidence=evidence,
        )
