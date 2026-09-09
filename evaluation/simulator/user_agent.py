"""模拟用户 Agent：输入 persona + 对话历史，输出用户下一句话。

- ``MockUserAgent``：按画像 script 顺序吐预置话术，耗尽后输出 FINISHED
  （CI 零 token）；
- ``LLMSimulatedUserAgent``：真实 LLM 扮演画像，prompt 显式注入
  persona.constraints（打错字/多需求/跑题等行为约束）与探针任务。
"""

from __future__ import annotations

from typing import List, Optional, Protocol

import structlog

from evaluation.llm_client import LLMClient
from evaluation.personas.base_persona import BasePersona

logger = structlog.get_logger(__name__)

FINISHED = "FINISHED"

#: 模拟用户系统提示（约束显式注入，任务书 M2 硬性要求）
SIM_USER_PROMPT = """你是一名真实电商运营人员，正在和内部 AI 助手对话。你要**扮演**这位运营，而不是扮演助手。

## 你的画像
- 姓名: {name}
- 角色: {role}
- 你的目标: {goal}
- 语气: {tone}
- 已有知识: {prior_knowledge}

## 行为约束（必须遵守，按描述的概率/方式执行）
{constraints_block}

## 对话策略
- 每次只输出你要说的**一句话**（中文，口语化，像真人发消息），不要输出助手的回复。
- 围绕你的目标推进对话；目标已达成时，输出 {finished} 结束对话。
- 第 {probe_hint}
- 最多还能说 {remaining_turns} 轮，注意节奏。

## 已有对话（你是"用户"）
{history_block}

现在输出你（用户）的下一句话。只输出这句话本身，不要任何解释、引号或前缀。
"""


class SimulatedUserAgent(Protocol):
    """模拟用户协议：产出下一句用户话术或 FINISHED。"""

    def invoke(self, persona: BasePersona, history: List[dict], turn: int) -> str: ...


class MockUserAgent:
    """mock 模式：script 顺序回放，耗尽输出 FINISHED。"""

    def invoke(self, persona: BasePersona, history: List[dict], turn: int) -> str:
        script = persona.script
        if turn <= len(script):
            return script[turn - 1]
        return FINISHED


class LLMSimulatedUserAgent:
    """real 模式：LLM 扮演画像生成下一句话。"""

    def __init__(self, client: LLMClient, max_turns: int = 8) -> None:
        self._client = client
        self._max_turns = max_turns

    def invoke(self, persona: BasePersona, history: List[dict], turn: int) -> str:
        constraints_block = "\n".join(
            f"- {c}" for c in persona.constraints
        ) or "- 无特殊约束，正常沟通"

        probes = persona.consistency_probes
        if probes:
            hint = "; ".join(
                f"第 {p.at_turn} 轮左右自然地问一句包含「{p.description or p.expect_reference}」的追问"
                for p in probes
            )
            probe_hint = f"对话后段（约第 {probes[-1].at_turn} 轮）请安排一致性追问：{hint}"
        else:
            probe_hint = "无追问任务，自然推进即可"

        history_block = "\n".join(
            f"{'用户' if m.get('role') == 'user' else '助手'}: {str(m.get('content', ''))[:300]}"
            for m in history[-12:]
        ) or "（对话刚开始，这是你的第一句话）"

        prompt = SIM_USER_PROMPT.format(
            name=persona.name,
            role=persona.role,
            goal=persona.goal,
            tone=persona.tone or "自然",
            prior_knowledge="; ".join(persona.prior_knowledge) or "基本运营常识",
            constraints_block=constraints_block,
            probe_hint=probe_hint,
            remaining_turns=max(1, self._max_turns - turn + 1),
            finished=FINISHED,
            history_block=history_block,
        )
        raw = self._client.invoke(prompt)
        text = raw.strip().strip('"').strip("'")
        if FINISHED in text:
            return FINISHED
        if not text:
            logger.warning("sim_user_empty_response", persona=persona.persona_id, turn=turn)
            return FINISHED
        return text


def build_user_agent(
    mode: str,
    client: Optional[LLMClient],
    max_turns: int = 8,
) -> SimulatedUserAgent:
    """工厂：mock → 脚本回放；real → LLM 扮演。"""

    if mode == "mock":
        return MockUserAgent()
    if client is None:
        raise ValueError("real 模式需要 LLMClient")
    return LLMSimulatedUserAgent(client, max_turns=max_turns)
