"""多轮编排器：自建 LangGraph 双 Agent 循环。

模拟用户节点（user_node）⇄ 被测 Agent 节点（agent_node）构成 StateGraph，
条件边执行三种终止条件（关键词 / 轮次上限 / 连续工具失败），
轨迹逐轮写入内存并在 episode 结束后落盘 JSONL。

核心循环（任务书 M2 伪代码的 LangGraph 化）::

    for turn in range(max_turns):
        user_msg = user_agent.invoke(persona, history)
        if stopping_met(user_msg): break
        agent_resp, trajectory = feishu_agent.invoke(user_msg)
        history.append(...)
        save_trajectory_jsonl(...)
"""

from __future__ import annotations

from typing import Dict, List, TypedDict

import structlog
from langgraph.graph import END, StateGraph

from evaluation.adapters.agent_adapter import AgentAdapter
from evaluation.config import EvalSettings
from evaluation.personas.base_persona import BasePersona
from evaluation.simulator.stopping_conditions import (
    evaluate_after_agent,
    evaluate_after_user,
)
from evaluation.simulator.user_agent import FINISHED, SimulatedUserAgent
from evaluation.trajectory import finish_trajectory, new_trajectory

logger = structlog.get_logger(__name__)


class SimState(TypedDict, total=False):
    """双 Agent 循环的图状态。"""

    persona: BasePersona
    trajectory: Dict[str, object]
    history: List[dict]           # [{"role": "user"|"assistant", "content": ...}]
    history_user_msgs: List[str]  # 仅供 mock 替身做"记忆"
    turn: int
    user_message: str
    llm_calls: int


class SimulationOrchestrator:
    """编排一个 episode：模拟用户 ⇄ 被测 Agent 多轮对话。"""

    def __init__(
        self,
        user_agent: SimulatedUserAgent,
        adapter: AgentAdapter,
        settings: EvalSettings,
    ) -> None:
        self._user_agent = user_agent
        self._adapter = adapter
        self._settings = settings
        self._graph = self._build_graph()

    # ============================================================
    # LangGraph 双 Agent 图
    # ============================================================
    def _build_graph(self):
        graph = StateGraph(SimState)
        graph.add_node("user_node", self._user_turn)
        graph.add_node("agent_node", self._agent_turn)
        graph.set_entry_point("user_node")
        graph.add_conditional_edges(
            "user_node",
            self._route_after_user,
            {"agent_node": "agent_node", "end": END},
        )
        graph.add_conditional_edges(
            "agent_node",
            self._route_after_agent,
            {"user_node": "user_node", "end": END},
        )
        return graph.compile()

    def _user_turn(self, state: SimState) -> Dict[str, object]:
        persona: BasePersona = state["persona"]
        traj: Dict[str, object] = state["trajectory"]
        turn = int(state.get("turn", 0)) + 1

        # 全局 LLM 断路器（real 模式防账单失控）
        llm_calls = int(state.get("llm_calls", 0)) + 1
        if self._settings.eval_mode == "real" and llm_calls > self._settings.max_llm_calls:
            finish_trajectory(traj, "llm_budget_exhausted")
            return {"turn": turn, "user_message": FINISHED, "llm_calls": llm_calls}

        user_message = self._user_agent.invoke(persona, state.get("history", []), turn)
        logger.debug(
            "sim_user_turn",
            persona=persona.persona_id,
            turn=turn,
            preview=user_message[:60],
        )
        return {"turn": turn, "user_message": user_message, "llm_calls": llm_calls}

    def _agent_turn(self, state: SimState) -> Dict[str, object]:
        traj: Dict[str, object] = state["trajectory"]
        turn = int(state.get("turn", 1))
        message = str(state.get("user_message", ""))

        record = self._adapter.send(
            message,
            conversation_id=str(traj.get("conversation_id", "eval")),
            history_user_msgs=list(state.get("history_user_msgs", [])),
        )
        record["turn"] = turn
        turns: List[dict] = traj.get("turns", [])  # type: ignore[assignment]
        turns.append(record)
        traj["turns"] = turns

        history: List[dict] = list(state.get("history", []))
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": str(record.get("agent_answer", ""))})
        history_user_msgs: List[str] = list(state.get("history_user_msgs", [])) + [message]

        return {
            "history": history,
            "history_user_msgs": history_user_msgs,
            "trajectory": traj,
        }

    # ---- 条件边：终止判定 ----
    def _route_after_user(self, state: SimState) -> str:
        persona: BasePersona = state["persona"]
        traj: Dict[str, object] = state["trajectory"]
        max_turns = persona.max_turns_override or self._settings.max_turns
        decision = evaluate_after_user(
            str(state.get("user_message", "")),
            int(state.get("turn", 1)),
            max_turns,
            traj.get("turns", []),  # type: ignore[arg-type]
        )
        if decision.stop:
            if decision.reason == "finished_keyword":
                finish_trajectory(traj, "finished_keyword")
            elif traj.get("termination", {}).get("reason"):  # type: ignore[union-attr]
                pass  # llm_budget 等已在 _user_turn 标记
            else:
                finish_trajectory(traj, decision.reason or "unknown")
            return "end"
        return "agent_node"

    def _route_after_agent(self, state: SimState) -> str:
        persona: BasePersona = state["persona"]
        traj: Dict[str, object] = state["trajectory"]
        max_turns = persona.max_turns_override or self._settings.max_turns
        decision = evaluate_after_agent(
            int(state.get("turn", 1)),
            max_turns,
            traj.get("turns", []),  # type: ignore[arg-type]
        )
        if decision.stop:
            finish_trajectory(traj, decision.reason or "unknown")
            return "end"
        return "user_node"

    # ============================================================
    # episode 入口
    # ============================================================
    def run_episode(
        self,
        persona: BasePersona,
        run_id: str,
        episode_index: int = 0,
    ) -> Dict[str, object]:
        """跑一个 episode，返回完整 trajectory dict。"""

        conversation_id = f"eval-{run_id}-{persona.persona_id}-e{episode_index}"
        traj = new_trajectory(
            run_id=run_id,
            persona_id=persona.persona_id,
            persona_name=persona.name,
            goal=persona.goal,
            mode=self._settings.eval_mode,
        )
        traj["conversation_id"] = conversation_id

        initial: SimState = {
            "persona": persona,
            "trajectory": traj,
            "history": [],
            "history_user_msgs": [],
            "turn": 0,
            "llm_calls": 0,
        }
        try:
            final_state = self._graph.invoke(
                initial, config={"recursion_limit": max(60, self._settings.max_turns * 8)}
            )
            result = final_state.get("trajectory", traj)  # type: ignore[return-value]
        except Exception as exc:  # noqa: BLE001 - 单 episode 崩溃不拖垮整个 run
            logger.error("episode_crashed", persona=persona.persona_id, error=str(exc))
            traj["error"] = str(exc)[:500]
            result = finish_trajectory(traj, "episode_error")

        # 兜底：任何路径离开都必须有终止原因
        term = result.get("termination") or {}
        if not term.get("reason"):
            finish_trajectory(result, "unknown")
        logger.info(
            "episode_done",
            persona=persona.persona_id,
            turns=result["termination"]["turns_used"],  # type: ignore[index]
            reason=result["termination"]["reason"],  # type: ignore[index]
        )
        return result


def build_orchestrator(
    user_agent: SimulatedUserAgent,
    adapter: AgentAdapter,
    settings: EvalSettings,
) -> SimulationOrchestrator:
    """工厂函数（CLI / 测试入口）。"""

    return SimulationOrchestrator(user_agent, adapter, settings)
