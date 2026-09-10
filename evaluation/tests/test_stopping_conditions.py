"""终止条件测试。"""

from evaluation.simulator.stopping_conditions import (
    consecutive_tool_failures,
    evaluate_after_agent,
    evaluate_after_user,
    is_finished_keyword,
    max_turns_exceeded,
)


def _turn(skill: str, rtype: str) -> dict:
    return {"turn": 1, "skill_results": [{"skill": skill, "type": rtype, "data": ""}]}


class TestStoppingConditions:
    def test_finished_keyword(self) -> None:
        assert is_finished_keyword("FINISHED") is True
        assert is_finished_keyword("帮我看下库存 FINISHED") is True
        assert is_finished_keyword("帮我看下库存") is False
        decision = evaluate_after_user("FINISHED", 3, 8, [])
        assert decision.stop and decision.reason == "finished_keyword"

    def test_max_turns_hard_limit(self) -> None:
        assert max_turns_exceeded(8, 8) is True
        assert max_turns_exceeded(7, 8) is False
        decision = evaluate_after_agent(turn=8, max_turns=8, turns=[_turn("x", "analysis")] * 8)
        assert decision.stop and decision.reason == "max_turns"

    def test_consecutive_tool_failures(self) -> None:
        one_failure = [_turn("a", "analysis"), _turn("a", "error")]
        assert consecutive_tool_failures(one_failure) is False
        two_failures = [_turn("a", "error"), _turn("a", "error")]
        assert consecutive_tool_failures(two_failures) is True
        # 空结果（Agent 崩溃轮）也算失败
        crashed = [{"turn": 1, "skill_results": []}, {"turn": 2, "skill_results": []}]
        assert consecutive_tool_failures(crashed) is True
        decision = evaluate_after_agent(turn=2, max_turns=8, turns=two_failures)
        assert decision.stop and decision.reason == "consecutive_tool_failures"

    def test_normal_progress_does_not_stop(self) -> None:
        turns = [_turn("a", "analysis"), _turn("b", "analysis")]
        assert evaluate_after_user("继续", 2, 8, turns).stop is False
        assert evaluate_after_agent(2, 8, turns).stop is False
