"""Evaluator 层：五个维度的评测器 + 注册表。"""

from typing import Dict, List, Optional

from evaluation.config import EvalSettings
from evaluation.evaluators.base import BaseEvaluator, EvalResult, load_prompt, parse_json_loose
from evaluation.evaluators.hallucination import HallucinationEvaluator
from evaluation.evaluators.multi_turn_consistency import MultiTurnConsistencyEvaluator
from evaluation.evaluators.safety_violation import SafetyViolationEvaluator
from evaluation.evaluators.task_completion import TaskCompletionEvaluator
from evaluation.evaluators.tool_calling_accuracy import ToolCallingAccuracyEvaluator
from evaluation.llm_client import LLMClient
from evaluation.personas.base_persona import BasePersona


def build_evaluators(
    settings: EvalSettings,
    judge: Optional[LLMClient] = None,
) -> List[BaseEvaluator]:
    """按配置实例化五个评测器（real 模式注入裁判 LLM）。"""

    return [
        TaskCompletionEvaluator(settings, judge),
        MultiTurnConsistencyEvaluator(settings, judge),
        ToolCallingAccuracyEvaluator(settings, judge),
        HallucinationEvaluator(settings, judge),
        SafetyViolationEvaluator(settings, judge),
    ]


def run_all_evaluators(
    evaluators: List[BaseEvaluator],
    trajectory: dict,
    persona: BasePersona,
) -> Dict[str, dict]:
    """对一个 episode 跑全部评测器，返回 {dimension: EvalResult.dict()}。

    单个评测器崩溃不阻塞其他维度（记 0 分并标注 evaluator_error）。
    """

    scores: Dict[str, dict] = {}
    for evaluator in evaluators:
        try:
            result: EvalResult = evaluator.evaluate(trajectory, persona)
            scores[evaluator.name] = result.model_dump()
        except Exception as exc:  # noqa: BLE001 - 评测器故障不拖垮整轮
            scores[evaluator.name] = EvalResult(
                score=0.0, passed=False,
                reason=f"evaluator_error: {str(exc)[:200]}",
            ).model_dump()
    return scores


__all__ = [
    "BaseEvaluator",
    "EvalResult",
    "HallucinationEvaluator",
    "MultiTurnConsistencyEvaluator",
    "SafetyViolationEvaluator",
    "TaskCompletionEvaluator",
    "ToolCallingAccuracyEvaluator",
    "build_evaluators",
    "load_prompt",
    "parse_json_loose",
    "run_all_evaluators",
]
