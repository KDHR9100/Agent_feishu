# -*- coding: utf-8 -*-
"""P1/P5 回归测试: 技能感知审批门 + 冲突仲裁接线

背景: 全量实测发现审批门纯关键词子串匹配会劫持创作/分析请求 (T02/T10/T11/R2),
以及 skill_executor 调 is_conflicted 时漏传原文导致 2 目标"既要又要"冲突静默失效 (P5)。
"""
from unittest.mock import patch


class TestSkillAwareGate:
    def test_non_executable_skills_never_gated(self):
        from app.utils import approval
        with patch.object(approval, "APPROVAL_ENABLED", True):
            # 分析/查询技能命中高危关键词也不门控 (P1: T02/T10/T11/R2)
            assert approval.should_gate("ads_skill", "降价促销的广告投放效果怎么样") is False
            assert approval.should_gate("competitor_skill", "竞品降价了，要不要跟进降价？") is False
            assert approval.should_gate("inventory_skill", "清仓的商品有哪些") is False
            assert approval.should_gate("report_skill", "出一份打折促销周报") is False

    def test_executable_skill_gated_on_high_risk_keywords(self):
        from app.utils import approval
        with patch.object(approval, "APPROVAL_ENABLED", True):
            assert approval.should_gate("pricing_skill", "把SKU-A001降价到99元") is True
            assert approval.should_gate("pricing_skill", "把价格下调10%，立刻执行") is True
            assert approval.should_gate("pricing_skill", "全场直降50元") is True

    def test_executable_skill_not_gated_without_keywords(self):
        from app.utils import approval
        with patch.object(approval, "APPROVAL_ENABLED", True):
            assert approval.should_gate("pricing_skill", "这个SKU定多少钱合适") is False

    def test_master_switch_off_never_gates(self):
        from app.utils import approval
        with patch.object(approval, "APPROVAL_ENABLED", False):
            assert approval.should_gate("pricing_skill", "降价到99元") is False
            assert approval.should_gate("ads_skill", "降价促销广告") is False

    def test_requires_approval_skills_still_forces_gate(self):
        from app.utils import approval
        with patch.object(approval, "APPROVAL_ENABLED", True), \
                patch.object(approval, "REQUIRES_APPROVAL_SKILLS", {"some_skill"}):
            assert approval.should_gate("some_skill", "随便聊聊") is True


class TestConflictWiring:
    """P5: skill_executor 必须把原文传给 is_conflicted, 2 目标显式并列句式才走仲裁"""

    def test_two_goal_explicit_conflict_routed_to_resolver(self):
        from app.agent.workflow import skill_executor
        state = {
            "tool_result": {"user_input": "我既要利润最大化又要销量最大化，帮我出个定价方案"},
            "conversation_id": "conv-conflict-2goal-wiring",
        }
        out = skill_executor(state)
        tr = out["tool_result"]
        assert tr["type"] == "conflict_decision"
        assert out["skill_results"][0]["skill"] == "conflict_resolver"

    def test_two_goal_without_connective_not_conflict(self):
        from app.optimizer.conflict_resolver import detect_conflicts, is_conflicted
        # 提到两个目标但非"两者兼得"诉求的描述性语句不判冲突
        text = "看看利润和销量的关系"
        assert is_conflicted(detect_conflicts(text), text) is False

    def test_three_goals_still_conflict(self):
        from app.optimizer.conflict_resolver import detect_conflicts, is_conflicted
        text = "省预算 + 保销量 + 清库存，帮我权衡一下"
        assert is_conflicted(detect_conflicts(text), text) is True
