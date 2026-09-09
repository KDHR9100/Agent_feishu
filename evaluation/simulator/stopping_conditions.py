"""终止条件：FINISHED 关键词 / 最大轮次硬上限 / 连续 2 轮工具调用失败。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

FINISHED_KEYWORD = "FINISHED"

#: 默认最大轮次（硬上限）
DEFAULT_MAX_TURNS = 8

#: 连续工具调用失败轮数阈值
CONSECUTIVE_FAILURE_LIMIT = 2


@dataclass(frozen=True)
class StopDecision:
    """终止判定结果：stop=True 时 reason 必填。"""

    stop: bool
    reason: Optional[str] = None


def is_finished_keyword(user_message: str) -> bool:
    """用户话术中包含 FINISHED 标记（LLM 模拟用户约定的结束信号）。"""

    return FINISHED_KEYWORD in (user_message or "")


def max_turns_exceeded(turn: int, max_turns: int = DEFAULT_MAX_TURNS) -> bool:
    """轮次达到硬上限。"""

    return turn >= max_turns


def _turn_failed(turn_record: dict) -> bool:
    """单轮是否算工具调用失败：全部技能结果 error，或无任何结果。

    注意：注入拦截轮（intent=injection_blocked）是预期安全行为，
    不算失败——否则攻击画像会在第 2 轮被误判"连续失败"提前终止。
    """

    if str(turn_record.get("intent", "")) == "injection_blocked":
        return False
    results = turn_record.get("skill_results") or []
    if not results:
        return True
    return all(str(r.get("type", "")) == "error" for r in results)


def consecutive_tool_failures(
    turns: List[dict],
    limit: int = CONSECUTIVE_FAILURE_LIMIT,
) -> bool:
    """连续 N 轮工具调用失败（被测 Agent 已不可用，继续问没有意义）。"""

    if len(turns) < limit:
        return False
    return all(_turn_failed(t) for t in turns[-limit:])


def evaluate_after_user(
    user_message: str,
    turn: int,
    max_turns: int,
    turns: List[dict],
) -> StopDecision:
    """用户发言后的终止判定（关键词 / 连续失败）。

    注意：轮次上限只在 agent 回复后判定（对齐任务书 ``for turn in range(max_turns)``
    语义——最后一轮用户消息应当得到回答）。
    """

    if is_finished_keyword(user_message):
        return StopDecision(stop=True, reason="finished_keyword")
    if consecutive_tool_failures(turns):
        return StopDecision(stop=True, reason="consecutive_tool_failures")
    return StopDecision(stop=False)


def evaluate_after_agent(
    turn: int,
    max_turns: int,
    turns: List[dict],
) -> StopDecision:
    """Agent 回复后的终止判定（轮次上限 / 连续失败）。"""

    if consecutive_tool_failures(turns):
        return StopDecision(stop=True, reason="consecutive_tool_failures")
    if max_turns_exceeded(turn, max_turns):
        return StopDecision(stop=True, reason="max_turns")
    return StopDecision(stop=False)
