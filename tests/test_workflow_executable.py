# -*- coding: utf-8 -*-
"""s6 工作流接线测试: pricing_skill 经 skill_executor 走 executor 审批闭环 (Checkpoint 3 链路)"""
import app.executor.action_verifier as av_mod
from app.agent.workflow import EXECUTABLE_SKILLS, SKILL_REGISTRY, _execute_single_skill
from app.utils.approval import HIGH_RISK_KEYWORDS, approval_manager


def test_pricing_skill_registered_and_executable():
    """约束: 不改原有 12 技能注册方式, pricing_skill 作为新增项挂载"""
    assert "pricing_skill" in SKILL_REGISTRY
    assert "pricing_skill" in EXECUTABLE_SKILLS
    assert len(EXECUTABLE_SKILLS) >= 1


def test_high_risk_keywords_cover_price_up_and_coupons():
    for kw in ["调高", "涨价", "提价", "发券"]:
        assert kw in HIGH_RISK_KEYWORDS


def test_executable_flow_approval_then_mock_execute(capsys):
    """Checkpoint 3 链路: 请求 -> 审批卡片(approval_required) -> 批准 -> Mock 执行成功"""
    verifier = av_mod.get_action_verifier()
    verifier.store._prices["default_hot_item"] = 99.0  # 重置 Mock 店铺价格

    state = {"conversation_id": "conv-checkpoint3"}
    result = _execute_single_skill(
        "pricing_skill",
        "帮我调高爆款价格 10%（当前售价 99，竞品均价 105）",
        None, None, {}, state,
    )
    # 1) 不直接执行, 返回审批请求
    assert result["type"] == "approval_required"
    aid = result["data"]["approval_id"]
    assert aid
    # 沙盒建议文本附在审批提示中
    assert "蒙特卡洛" in result["data"]["response"]
    assert "高风险" in result["data"]["response"]
    # 审批前价格不变
    assert verifier.store.get_price("default_hot_item") == 99.0

    # 2) 模拟飞书卡片点击批准
    assert approval_manager.resolve(aid, True) is True
    receipt = approval_manager.take_and_execute(aid)
    assert receipt is not None
    assert receipt["success"] is True
    # 3) Mock 店铺价格已按沙盒最优方案调整
    assert verifier.store.get_price("default_hot_item") == receipt["new_price"]
    out = capsys.readouterr().out
    assert "模拟修改价格成功" in out
    assert "Mock 执行成功" in out
    # 4) 回滚窗口已登记
    assert receipt.get("action_id")
    assert verifier.rollback.get(receipt["action_id"])["status"] == "awaiting_confirmation"


def test_executable_flow_reject_keeps_price(capsys):
    verifier = av_mod.get_action_verifier()
    verifier.store._prices["default_hot_item"] = 99.0
    state = {"conversation_id": "conv-reject"}
    result = _execute_single_skill(
        "pricing_skill", "帮我定价，当前售价 99，竞品均价 105", None, None, {}, state)
    assert result["type"] == "approval_required"
    aid = result["data"]["approval_id"]
    approval_manager.resolve(aid, False)
    assert approval_manager.take_and_execute(aid) is None
    assert verifier.store.get_price("default_hot_item") == 99.0
