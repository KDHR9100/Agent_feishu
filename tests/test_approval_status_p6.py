# -*- coding: utf-8 -*-
"""P6 回归测试: 最近审批台账 + answer_node 审批状态注入

背景: 审批被拒/已执行后用户追问进展, bot 曾回答"等待审批中"(AP33b)或"查不到进度",
修复方案为 ApprovalManager 增加最近审批台账, answer_node 在追问时注入真实状态。
"""
import uuid
from unittest.mock import patch


def _uniq_conv(prefix):
    return "%s-%s" % (prefix, uuid.uuid4().hex[:8])


class TestApprovalLedger:
    def test_rejected_approval_recorded(self):
        from app.utils.approval import approval_manager, recent_approval_summary
        conv = _uniq_conv("conv-rej")
        aid = approval_manager.create_approval(
            action_name="pricing_skill", action_func=lambda: None,
            conversation_id=conv, description="把SKU-A001降价到99元")
        assert approval_manager.resolve(aid, approved=False) is True
        items = approval_manager.recent_approvals(conv)
        assert items and items[0]["approval_id"] == aid
        assert items[0]["status"] == "rejected"
        summary = recent_approval_summary(conv)
        assert "已拒绝" in summary and aid in summary

    def test_approved_and_executed_recorded(self):
        from app.utils.approval import approval_manager, recent_approval_summary
        conv = _uniq_conv("conv-exec")
        aid = approval_manager.create_approval(
            action_name="pricing_skill", action_func=lambda: "done",
            conversation_id=conv, description="把价格下调10%")
        assert approval_manager.resolve(aid, approved=True) is True
        assert approval_manager.take_and_execute(aid) == "done"
        summary = recent_approval_summary(conv)
        assert "已批准并已执行" in summary

    def test_pending_approval_visible(self):
        from app.utils.approval import approval_manager, recent_approval_summary
        conv = _uniq_conv("conv-pend")
        approval_manager.create_approval(
            action_name="pricing_skill", action_func=lambda: None,
            conversation_id=conv, description="改价到99")
        summary = recent_approval_summary(conv)
        assert "等待审批中" in summary

    def test_conversation_scope_isolation(self):
        from app.utils.approval import approval_manager, recent_approval_summary
        conv_a, conv_b = _uniq_conv("conv-a"), _uniq_conv("conv-b")
        aid = approval_manager.create_approval(
            action_name="pricing_skill", action_func=lambda: None,
            conversation_id=conv_a, description="A会话的审批")
        approval_manager.resolve(aid, approved=False)
        # B 会话查询不应命中 A 会话的记录 (无记录时退回全局最近, 但此处 A 记录非 pending)
        items_b = approval_manager.recent_approvals(conv_b)
        assert all(e.get("conversation_id") != conv_a or e["approval_id"] != aid
                   for e in items_b if e.get("conversation_id") == conv_b)


class TestAnswerNodeInjection:
    def test_followup_gets_real_status(self):
        from app.agent.workflow import answer_node
        from app.utils.approval import approval_manager
        conv = _uniq_conv("conv-ask")
        aid = approval_manager.create_approval(
            action_name="pricing_skill", action_func=lambda: None,
            conversation_id=conv, description="SKU-A001降价审批")
        approval_manager.resolve(aid, approved=False)
        state = {
            "conversation_id": conv,
            "user_input": "刚才那个审批通过了吗？执行了没",
            "skill_results": [
                {"skill": "support_skill",
                 "result": {"type": "text", "data": "工单系统暂时无法访问, 无法查询进度"}},
            ],
        }
        out = answer_node(state)
        # AP33b 修复后: 台账已有明确裁决时直接用确定性状态答复覆盖, 不再仅前置记录
        assert "已被拒绝" in out["answer"]
        assert "未执行" in out["answer"]
        assert "等待审批中" not in out["answer"]

    def test_no_followup_no_injection(self):
        from app.agent.workflow import answer_node
        state = {
            "conversation_id": _uniq_conv("conv-normal"),
            "user_input": "帮我优化商品标题",
            "skill_results": [
                {"skill": "seo_skill", "result": {"type": "text", "data": "这是优化后的标题"}},
            ],
        }
        out = answer_node(state)
        assert "最近审批记录" not in out["answer"]

    def test_new_approval_card_not_double_annotated(self):
        from app.agent.workflow import answer_node
        state = {
            "conversation_id": _uniq_conv("conv-card"),
            "user_input": "把SKU-A001降价到99元, 等你审批通过",
            "skill_results": [
                {"skill": "pricing_skill",
                 "result": {"type": "approval_required",
                            "data": {"response": "已发送审批卡片", "approval_id": "x"}}},
            ],
        }
        out = answer_node(state)
        assert "最近审批记录" not in out["answer"]
