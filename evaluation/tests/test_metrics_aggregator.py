"""指标聚合器测试。"""

from evaluation.config import EvalSettings
from evaluation.reports import aggregate, aggregate_by_dimension


def _settings(**overrides) -> EvalSettings:
    base = {"eval_mode": "mock"}
    base.update(overrides)
    return EvalSettings(**base)


def _episode(pid: str, scores: dict, expected: list = None, error: str = None) -> dict:
    return {
        "persona_id": pid, "goal": "g", "mode": "mock", "error": error,
        "turns": [
            {"turn": 1, "user_message": "u", "agent_answer": "a", "intent": "i",
             "skills_to_execute": expected or [], "skill_results": []},
        ],
        "termination": {"reason": "finished_keyword", "turns_used": 1},
        "_expected_tools": expected or [],
        "scores": scores,
    }


class TestMetricsAggregator:
    def test_by_dimension_averaging_and_failed_personas(self) -> None:
        episodes = [
            _episode("a", {"task_completion": {"score": 1.0, "passed": True, "skipped": False}}),
            _episode("b", {"task_completion": {"score": 0.5, "passed": False, "skipped": False}}),
        ]
        result = aggregate_by_dimension(episodes, _settings())
        assert result["task_completion"]["score"] == 0.75
        assert result["task_completion"]["failed_personas"] == ["b"]

    def test_safety_gate_trips_overall_to_zero(self) -> None:
        episodes = [
            _episode("a", {
                "safety_violation": {"score": 0.5, "passed": False, "skipped": False},
                "task_completion": {"score": 1.0, "passed": True, "skipped": False},
            }),
        ]
        metrics = aggregate(episodes, _settings())
        assert metrics["safety_gate_tripped"] is True
        assert metrics["overall"] == 0.0
        assert metrics["passed"] is False

    def test_skipped_dimensions_excluded(self) -> None:
        episodes = [
            _episode("a", {
                "multi_turn_consistency": {"score": 0.0, "passed": False, "skipped": True},
                "task_completion": {"score": 1.0, "passed": True, "skipped": False},
            }),
        ]
        result = aggregate_by_dimension(episodes, _settings())
        assert result["multi_turn_consistency"]["score"] is None
        metrics = aggregate(episodes, _settings())
        # 只有 task_completion 一个有效维 → 总分即该维得分
        assert metrics["overall"] == 1.0

    def test_by_turn_tool_correct_rate(self) -> None:
        a = _episode("a", {}, expected=["inventory_skill"])
        b = {
            "persona_id": "b", "goal": "g", "mode": "mock", "error": None,
            "turns": [
                {"turn": 1, "user_message": "u", "agent_answer": "a", "intent": "ads_skill",
                 "skills_to_execute": ["ads_skill"], "skill_results": []},
            ],
            "termination": {"reason": "finished_keyword", "turns_used": 1},
            "_expected_tools": [],  # 无预期却调了工具 → 该轮算错
            "scores": {},
        }
        metrics = aggregate([a, b], _settings())
        turn1 = metrics["by_turn"]["1"]
        assert turn1["episodes"] == 2
        # a 调了预期内工具 ✓, b 无预期却调了工具 ✗ → 50%
        assert turn1["tool_correct_rate"] == 0.5

    def test_all_skipped_episode_passes_and_not_failed(self) -> None:
        episodes = [
            _episode("attacker", {
                "safety_violation": {"score": 1.0, "passed": True, "skipped": True},
            }, expected=[]),
        ]
        metrics = aggregate(episodes, _settings())
        info = metrics["by_persona"]["attacker"]
        assert info["weighted_score"] is None
        assert info["passed"] is True
