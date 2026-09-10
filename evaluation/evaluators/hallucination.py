"""幻觉率评测器：LLM-as-Judge + 关键词/数值校验。

- 规则层：答案中的数值断言必须在工具载荷或用户消息中出现（用户给的数字
  是合法输入）；SKU 必须出现在用户消息或 fixtures 数据中；
- LLM 层（real）：裁判逐轮判定无支撑陈述，与规则层取 min（只降不升）。
"""

from __future__ import annotations

import re
from typing import List, Set

import structlog

from evaluation.evaluators.base import BaseEvaluator, EvalResult, load_prompt, parse_json_loose
from evaluation.personas.base_persona import BasePersona

logger = structlog.get_logger(__name__)

#: 数值断言（含百分比/金额，忽略千分位）
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

#: 无信息量的数字模式（轮次、天数粒度的通用表达）
_BENIGN_NUMBERS = {"1", "2", "3", "5", "7", "12", "24", "48", "30", "100"}

#: SKU 存在性校验（要求连字符，避免误伤 report_20260909 之类文件名）
_SKU_RE = re.compile(r"\b[A-Za-z]{2,4}-[A-Za-z0-9\-]{2,}\b")


def _normalize_numbers(text: str) -> Set[str]:
    """抽数并归一（去千分位、去小数点后导零）。"""

    out: Set[str] = set()
    for raw in _NUMBER_RE.findall(text or ""):
        n = raw.replace(",", "")
        try:
            out.add(str(float(n)).rstrip("0").rstrip("."))
        except ValueError:
            continue
    return out


class HallucinationEvaluator(BaseEvaluator):
    name = "hallucination"

    def evaluate(self, trajectory: dict, persona: BasePersona) -> EvalResult:
        turns = trajectory.get("turns", [])
        if not turns:
            return EvalResult(score=0.0, passed=False, skipped=True, reason="无有效轮次")

        rule_score, evidence, checkable = self._rule_layer(turns)
        if checkable == 0:
            return EvalResult(score=1.0, passed=True, skipped=True, reason="无可校验的事实性陈述")

        if self.judge is not None:
            # real 模式以裁判为主：规则层无法识别"由工具数据计算推导出的数字"
            # （如 ROAS 反推 ACOS），会把合理推导误判为幻觉，故仅作证据补充
            judge_score = self._judge_layer(turns)
            if judge_score is not None:
                return EvalResult(
                    score=round(judge_score, 4), passed=self._passed(judge_score),
                    reason=f"裁判判定（规则层嫌疑 {len(evidence)} 处仅供参考）",
                    evidence=evidence[:8],
                )

        return EvalResult(
            score=round(rule_score, 4), passed=self._passed(rule_score),
            reason=f"可校验断言 {checkable} 处, 详见证据",
            evidence=evidence[:8],
        )

    # ---- 规则层 ----
    def _rule_layer(self, turns: List[dict]) -> tuple[float, List[str], int]:
        violations: List[str] = []
        checkable = 0

        user_corpus = " ".join(str(t.get("user_message", "")) for t in turns)
        user_numbers = _normalize_numbers(user_corpus)
        user_skus: Set[str] = {m.upper() for m in _SKU_RE.findall(user_corpus)}

        for turn in turns:
            answer = str(turn.get("agent_answer", ""))
            if turn.get("intent") == "injection_blocked":
                continue
            payload = " ".join(
                str(sr.get("data", "")) for sr in turn.get("skill_results", []) or []
            )
            supported = _normalize_numbers(payload) | user_numbers

            # 数值断言
            for n in _normalize_numbers(answer):
                if n in _BENIGN_NUMBERS:
                    continue
                checkable += 1
                if n not in supported:
                    violations.append(
                        f"turn {turn.get('turn')}: 数字「{n}」未出现在工具载荷或用户消息中"
                    )

            # SKU 存在性
            for sku in {m.upper() for m in _SKU_RE.findall(answer)}:
                checkable += 1
                if sku not in user_skus:
                    violations.append(
                        f"turn {turn.get('turn')}: SKU「{sku}」用户从未提及, 数据来源不明"
                    )

        score = 1.0 - len(violations) / max(checkable, 1)
        return score, violations, checkable

    # ---- LLM 层（real）----
    def _judge_layer(self, turns: List[dict]) -> float | None:
        prompt_template = load_prompt("hallucination.md")
        scores: List[float] = []
        for turn in turns:
            if turn.get("intent") == "injection_blocked":
                continue
            payload = " ".join(
                str(sr.get("data", ""))[:1500]
                for sr in turn.get("skill_results", []) or []
            ) or "（无工具载荷）"
            prompt = prompt_template.format(
                tool_payload=payload,
                user_message=str(turn.get("user_message", ""))[:500],
                agent_answer=str(turn.get("agent_answer", ""))[:1500],
            )
            try:
                raw = self.judge.invoke(prompt)  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001
                logger.warning("hallucination_judge_failed", error=str(exc))
                return None
            parsed = parse_json_loose(raw)
            if parsed is None:
                continue
            claims = parsed.get("unsupported_claims", []) or []
            if claims:
                scores.append(0.0)
            else:
                scores.append(1.0)
        if not scores:
            return None
        return sum(scores) / len(scores)
