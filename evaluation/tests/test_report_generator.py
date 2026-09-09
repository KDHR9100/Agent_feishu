"""报告生成器测试。"""

import json
from pathlib import Path

from evaluation.config import EvalSettings
from evaluation.reports import generate_reports, load_previous_run


def _settings(**overrides) -> EvalSettings:
    base = {"eval_mode": "mock"}
    base.update(overrides)
    return EvalSettings(**base)


def _episode(pid: str, score: float) -> dict:
    return {
        "run_id": "run-x", "persona_id": pid, "persona_name": "测试", "goal": "目标",
        "mode": "mock", "error": None,
        "turns": [
            {"turn": 1, "user_message": "看下库存", "agent_answer": "库存 500 件",
             "intent": "inventory_skill", "skills_to_execute": ["inventory_skill"],
             "skill_results": [{"skill": "inventory_skill", "type": "analysis", "data": "库存 500 件"}],
             "execution_plan": None, "reflect_decision": "sufficient", "retry_rounds": 0,
             "token_usage": {}, "node_timings_ms": {}, "safety_events": []},
        ],
        "termination": {"reason": "finished_keyword", "turns_used": 1},
        "scores": {
            "task_completion": {"score": score, "passed": score >= 0.75, "skipped": False},
            "multi_turn_consistency": {"score": 1.0, "passed": True, "skipped": True},
            "tool_calling_accuracy": {"score": 1.0, "passed": True, "skipped": False},
            "hallucination": {"score": 1.0, "passed": True, "skipped": False},
            "safety_violation": {"score": 1.0, "passed": True, "skipped": True},
        },
    }


class TestReportGenerator:
    def test_generates_md_html_and_history(self, tmp_path: Path) -> None:
        episodes = [_episode("p1", 1.0)]
        metrics = {
            "overall": 1.0, "passed": True, "safety_gate_tripped": False,
            "episode_count": 1, "error_episodes": [],
            "by_dimension": {
                "task_completion": {"score": 1.0, "threshold": 0.75, "passed": True,
                                    "episodes": 1, "failed_personas": []},
            },
            "by_persona": {"p1": {"weighted_score": 1.0, "turns_used": 1,
                                  "termination": "finished_keyword", "passed": True}},
            "by_turn": {"1": {"episodes": 1, "tool_correct_rate": 1.0}},
        }
        paths = generate_reports("run-a", episodes, metrics, _settings(), tmp_path)
        assert paths["markdown"].exists() and paths["html"].exists()
        md = paths["markdown"].read_text(encoding="utf-8")
        assert "五维总览" in md and "p1" in md and "MODE=mock" in md
        html = paths["html"].read_text(encoding="utf-8")
        assert "eval-data" in html and "p1" in html
        # history 落盘且可读回
        prev = load_previous_run(tmp_path / "history", exclude_run_id="run-other")
        assert prev is not None and prev["run_id"] == "run-a"

    def test_comparison_with_previous_run(self, tmp_path: Path) -> None:
        settings = _settings()
        metrics = {
            "overall": 0.9, "passed": True, "safety_gate_tripped": False,
            "episode_count": 1, "error_episodes": [],
            "by_dimension": {
                "task_completion": {"score": 0.9, "threshold": 0.75, "passed": True,
                                    "episodes": 1, "failed_personas": []},
            },
            "by_persona": {"p1": {"weighted_score": 0.9, "turns_used": 1,
                                  "termination": "finished_keyword", "passed": True}},
            "by_turn": {"1": {"episodes": 1, "tool_correct_rate": 1.0}},
        }
        # 第一次 run
        generate_reports("run-1", [_episode("p1", 0.8)], metrics, settings, tmp_path)
        # 第二次 run 应包含对比段落
        paths = generate_reports("run-2", [_episode("p1", 0.9)], metrics, settings, tmp_path)
        md = paths["markdown"].read_text(encoding="utf-8")
        assert "与上次 run 对比" in md and "run-1" in md
        prev = load_previous_run(tmp_path / "history", exclude_run_id="run-2")
        assert prev["run_id"] == "run-1"

    def test_failure_case_contains_trajectory(self, tmp_path: Path) -> None:
        episodes = [_episode("bad_persona", 0.2)]
        metrics = {
            "overall": 0.2, "passed": False, "safety_gate_tripped": False,
            "episode_count": 1, "error_episodes": [],
            "by_dimension": {
                "task_completion": {"score": 0.2, "threshold": 0.75, "passed": False,
                                    "episodes": 1, "failed_personas": ["bad_persona"]},
            },
            "by_persona": {"bad_persona": {"weighted_score": 0.2, "turns_used": 1,
                                           "termination": "finished_keyword", "passed": False}},
            "by_turn": {"1": {"episodes": 1, "tool_correct_rate": 1.0}},
        }
        paths = generate_reports("run-f", episodes, metrics, _settings(), tmp_path)
        md = paths["markdown"].read_text(encoding="utf-8")
        assert "失败 Top" in md
        assert "完整 trajectory" in md
        assert json.loads((tmp_path / "history" / "run-f.jsonl").read_text(encoding="utf-8"))["run_id"] == "run-f"
