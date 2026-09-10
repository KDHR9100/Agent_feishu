"""Simulator 层：模拟用户 Agent + LangGraph 双 Agent 编排器 + 终止条件。"""

from evaluation.simulator.orchestrator import SimState, SimulationOrchestrator, build_orchestrator
from evaluation.simulator.stopping_conditions import (
    CONSECUTIVE_FAILURE_LIMIT,
    DEFAULT_MAX_TURNS,
    StopDecision,
    consecutive_tool_failures,
    evaluate_after_agent,
    evaluate_after_user,
    is_finished_keyword,
    max_turns_exceeded,
)
from evaluation.simulator.user_agent import (
    FINISHED,
    LLMSimulatedUserAgent,
    MockUserAgent,
    SimulatedUserAgent,
    build_user_agent,
)

__all__ = [
    "CONSECUTIVE_FAILURE_LIMIT",
    "DEFAULT_MAX_TURNS",
    "FINISHED",
    "LLMSimulatedUserAgent",
    "MockUserAgent",
    "SimState",
    "SimulatedUserAgent",
    "SimulationOrchestrator",
    "StopDecision",
    "build_orchestrator",
    "build_user_agent",
    "consecutive_tool_failures",
    "evaluate_after_agent",
    "evaluate_after_user",
    "is_finished_keyword",
    "max_turns_exceeded",
]
