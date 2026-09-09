"""模拟用户 Agent 测试（任务书要求至少 2 个：正常 / 终止）。"""

import pytest

from evaluation.llm_client import ScriptedLLMClient
from evaluation.personas import load_personas
from evaluation.simulator import FINISHED, LLMSimulatedUserAgent, MockUserAgent, build_user_agent


def _persona():
    return load_personas()[0]


class TestMockUserAgent:
    def test_script_playback_then_finished(self) -> None:
        persona = _persona()
        agent = MockUserAgent()
        first = agent.invoke(persona, [], 1)
        assert first == persona.script[0]
        # 超出 script 长度后输出 FINISHED
        exhausted = agent.invoke(persona, [], len(persona.script) + 1)
        assert exhausted == FINISHED


class TestLLMSimulatedUserAgent:
    def test_prompt_injects_constraints_explicitly(self) -> None:
        persona = _persona()
        assert persona.constraints, "测试画像必须带 constraints"
        client = ScriptedLLMClient(["帮我看下库存"])
        agent = LLMSimulatedUserAgent(client, max_turns=8)
        message = agent.invoke(persona, [], 1)
        # prompt 必须显式包含行为约束段落（任务书 M2 硬性要求）
        prompt = client.prompts[0]
        assert "行为约束" in prompt
        assert persona.constraints[0] in prompt
        assert persona.goal in prompt
        assert message == "帮我看下库存"

    def test_finished_passthrough(self) -> None:
        persona = _persona()
        client = ScriptedLLMClient(["FINISHED"])
        agent = LLMSimulatedUserAgent(client, max_turns=8)
        assert agent.invoke(persona, [], 3) == FINISHED

    def test_missing_client_in_real_mode_raises(self) -> None:
        with pytest.raises(ValueError):
            build_user_agent("real", None, 8)
