"""编排器测试（任务书要求至少 2 个：正常 / 超轮次终止）。"""

from pathlib import Path
from typing import Dict, List, Optional

from evaluation.adapters.agent_adapter import MockFeishuAgent
from evaluation.config import EvalSettings
from evaluation.personas import load_personas
from evaluation.simulator import MockUserAgent, build_orchestrator
from evaluation.trajectory import TrajectoryWriter, read_jsonl


class _FailingAdapter:
    """连续失败的被测 Agent 替身。"""

    def send(
        self, message: str, conversation_id: str,
        history_user_msgs: Optional[List[str]] = None,
    ) -> Dict[str, object]:
        return {
            "turn": 0, "user_message": message,
            "agent_answer": "技能 x 执行出错, 请稍后重试。", "intent": "error",
            "skills_to_execute": ["x"],
            "skill_results": [{"skill": "x", "type": "error", "data": "boom"}],
            "execution_plan": None, "reflect_decision": "sufficient", "retry_rounds": 0,
            "token_usage": {}, "node_timings_ms": {}, "safety_events": [],
        }


def _settings(**overrides) -> EvalSettings:
    base = {"eval_mode": "mock", "max_turns": 8}
    base.update(overrides)
    return EvalSettings(**base)


class TestOrchestrator:
    def test_mock_episode_full_run(self, tmp_path: Path) -> None:
        persona = load_personas()[0]  # temu_operator
        settings = _settings()
        orchestrator = build_orchestrator(MockUserAgent(), MockFeishuAgent(), settings)
        episode = orchestrator.run_episode(persona, "run-test", 0)

        assert episode["persona_id"] == persona.persona_id
        assert episode["termination"]["reason"] == "finished_keyword"
        assert episode["termination"]["turns_used"] == len(persona.script)
        assert len(episode["turns"]) == len(persona.script)
        for turn in episode["turns"]:
            assert turn["user_message"]
            assert turn["agent_answer"]
            assert turn["intent"]

        # JSONL 落盘可读
        path = tmp_path / "trajectory.jsonl"
        with TrajectoryWriter(path) as writer:
            writer.write(episode)
        rows = list(read_jsonl(path))
        assert len(rows) == 1 and rows[0]["persona_id"] == persona.persona_id

    def test_max_turns_termination(self) -> None:
        persona = load_personas()[0]
        persona = persona.model_copy(update={"max_turns_override": 2})
        settings = _settings()
        orchestrator = build_orchestrator(MockUserAgent(), MockFeishuAgent(), settings)
        episode = orchestrator.run_episode(persona, "run-max", 0)
        assert episode["termination"]["reason"] == "max_turns"
        assert episode["termination"]["turns_used"] == 2

    def test_consecutive_failure_termination(self) -> None:
        persona = load_personas()[0]
        settings = _settings()
        orchestrator = build_orchestrator(MockUserAgent(), _FailingAdapter(), settings)
        episode = orchestrator.run_episode(persona, "run-fail", 0)
        assert episode["termination"]["reason"] == "consecutive_tool_failures"
        assert episode["termination"]["turns_used"] == 2
