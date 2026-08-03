# -*- coding: utf-8 -*-
"""s5 执行器测试: Mock 后端 / 强制审批 / 5分钟超时放弃 / 执行后回执 / 1小时自动回滚"""
import time

import pytest

import app.config
import app.executor.platform_adapter as platform_adapter
from app.executor.action_verifier import HIGH_RISK_ACTIONS, ActionVerifier
from app.executor.platform_adapter import MockStoreAPI, TmallStoreAPI, get_store_api
from app.executor.rollback_manager import RollbackManager
from app.utils.approval import ApprovalManager


@pytest.fixture
def env():
    store = MockStoreAPI()
    rollback = RollbackManager(store_api=store, auto_start=False)
    approvals = ApprovalManager()
    verifier = ActionVerifier(
        store_api=store, rollback_manager=rollback, approvals=approvals)
    return store, rollback, approvals, verifier


PRICE_REQ = {
    "action": "update_price",
    "params": {"product_id": "default_hot_item", "new_price": 120.0},
    "description": "调高爆款价格测试",
}


# ---------- platform_adapter ----------
def test_mock_store_update_price(env):
    store = env[0]
    receipt = store.update_price("default_hot_item", 88.0)
    assert receipt["success"] is True
    assert receipt["old_price"] == 99.0
    assert store.get_price("default_hot_item") == 88.0


def test_mock_store_illegal_price(env):
    receipt = env[0].update_price("default_hot_item", -5)
    assert receipt["success"] is False


def test_get_store_api_default_mock():
    """硬约束: 未显式设置 EXECUTOR_REAL_MODE=true 时必须为 Mock"""
    assert app.config.EXECUTOR_REAL_MODE is False
    assert get_store_api().platform == "mock"


def test_real_mode_returns_real_adapter_and_blocks(monkeypatch):
    monkeypatch.setattr(platform_adapter, "EXECUTOR_REAL_MODE", True)
    monkeypatch.setenv("STORE_PLATFORM", "tmall")
    api = get_store_api()
    assert isinstance(api, TmallStoreAPI)
    with pytest.raises(NotImplementedError):
        api.update_price("p1", 100)


# ---------- action_verifier ----------
def test_three_high_risk_actions_defined():
    assert HIGH_RISK_ACTIONS == {"update_price", "batch_send_coupons", "delist_product"}


def test_high_risk_requires_approval_before_execution(env, capsys):
    store, rollback, approvals, verifier = env
    result = verifier.verify_and_execute(PRICE_REQ, skill_name="pricing_skill")
    assert result["type"] == "approval_required"
    aid = result["data"]["approval_id"]
    # 审批前: 价格绝未被修改
    assert store.get_price("default_hot_item") == 99.0

    # 模拟飞书卡片点击批准: resolve -> take_and_execute (后台执行)
    assert approvals.resolve(aid, True) is True
    receipt = approvals.take_and_execute(aid)
    assert receipt["success"] is True
    assert store.get_price("default_hot_item") == 120.0

    out = capsys.readouterr().out
    assert "模拟修改价格成功" in out
    assert "Mock 执行成功" in out

    # 执行后回执: 回滚窗口已登记旧值
    rec = rollback.get(receipt["action_id"])
    assert rec["status"] == "awaiting_confirmation"
    assert rec["old_values"]["old_price"] == 99.0


def test_approval_timeout_abandons_execution(env):
    store, rollback, approvals, verifier = env
    result = verifier.verify_and_execute(PRICE_REQ)
    aid = result["data"]["approval_id"]
    # 模拟超过 5 分钟(APPROVAL_TIMEOUT=300s)无人审批
    approvals._pending[aid]["created_at"] -= 400
    approvals.resolve(aid, True)
    assert approvals.take_and_execute(aid) is None
    # 默认放弃执行: 价格不变
    assert store.get_price("default_hot_item") == 99.0


def test_reject_blocks_execution(env):
    store, rollback, approvals, verifier = env
    result = verifier.verify_and_execute(PRICE_REQ)
    aid = result["data"]["approval_id"]
    approvals.resolve(aid, False)
    assert approvals.take_and_execute(aid) is None
    assert store.get_price("default_hot_item") == 99.0


def test_delist_and_batch_coupons_also_gated(env):
    store, rollback, approvals, verifier = env
    r1 = verifier.verify_and_execute(
        {"action": "delist_product", "params": {"product_id": "default_hot_item"}})
    r2 = verifier.verify_and_execute(
        {"action": "batch_send_coupons", "params": {"coupon": "满100减20", "count": 500}})
    assert r1["type"] == "approval_required"
    assert r2["type"] == "approval_required"


# ---------- rollback_manager ----------
def _approve_and_execute(verifier, approvals, req):
    aid = verifier.verify_and_execute(req)["data"]["approval_id"]
    approvals.resolve(aid, True)
    return approvals.take_and_execute(aid)


def test_auto_rollback_when_not_confirmed(env):
    store = env[0]
    approvals = ApprovalManager()
    rb = RollbackManager(store_api=store, confirm_window_seconds=0.05, auto_start=False)
    verifier = ActionVerifier(store_api=store, rollback_manager=rb, approvals=approvals)
    receipt = _approve_and_execute(verifier, approvals, PRICE_REQ)
    assert store.get_price("default_hot_item") == 120.0

    time.sleep(0.08)  # 超过确认窗口
    rolled = rb.sweep_once()
    assert receipt["action_id"] in rolled
    assert store.get_price("default_hot_item") == 99.0  # 自动调回原价


def test_confirm_prevents_rollback(env):
    store = env[0]
    approvals = ApprovalManager()
    rb = RollbackManager(store_api=store, confirm_window_seconds=0.05, auto_start=False)
    verifier = ActionVerifier(store_api=store, rollback_manager=rb, approvals=approvals)
    receipt = _approve_and_execute(verifier, approvals, PRICE_REQ)

    assert rb.confirm(receipt["action_id"]) is True
    time.sleep(0.08)
    assert rb.sweep_once() == []
    assert store.get_price("default_hot_item") == 120.0  # 人工确认后保持新价


def test_coupons_not_auto_rollbackable(env):
    store = env[0]
    approvals = ApprovalManager()
    rb = RollbackManager(store_api=store, confirm_window_seconds=0.05, auto_start=False)
    verifier = ActionVerifier(store_api=store, rollback_manager=rb, approvals=approvals)
    receipt = _approve_and_execute(
        verifier, approvals,
        {"action": "batch_send_coupons", "params": {"coupon": "满100减20"}})
    assert receipt["success"] is True
    time.sleep(0.08)
    assert rb.sweep_once() == []  # 券不可自动回滚, 需人工介入
    assert rb.get(receipt["action_id"])["status"] == "rollback_failed"


def test_double_rollback_safe(env):
    store, rollback, approvals, verifier = env
    receipt = _approve_and_execute(verifier, approvals, PRICE_REQ)
    action_id = receipt["action_id"]
    assert rollback.rollback(action_id)["success"] is True
    assert rollback.rollback(action_id)["success"] is False  # 幂等保护
    assert store.get_price("default_hot_item") == 99.0
