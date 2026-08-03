# -*- coding: utf-8 -*-
"""s10 第 1 轮压测: 边界值与异常输入 (用例与既有测试完全不重复)"""
import pytest

from app.config import EXECUTOR_REAL_MODE, OPTIMIZER_CONFIG
from app.executor.action_verifier import ActionVerifier
from app.executor.platform_adapter import MockStoreAPI, get_store_api
from app.executor.rollback_manager import RollbackManager
from app.optimizer.conflict_resolver import ConflictResolver, detect_conflicts, is_conflicted
from app.optimizer.profit_model import estimate_profit
from app.optimizer.solver_engine import solve
from app.sentinel.crawler_base import MockMarketStore, MockTmallCrawler
from app.sentinel.event_bus import EventBus, MARKET_ALERT
from app.sentinel.trigger_engine import MarketSentinel
from app.utils.approval import ApprovalManager


def _mk_sentinel():
    store = MockMarketStore()
    bus = EventBus()
    sentinel = MarketSentinel(crawler=MockTmallCrawler(store=store), bus=bus, store=store)
    return store, bus, sentinel


# ---------- 哨兵阈值边界 ----------
def test_price_change_exactly_3pct_alerts():
    store, bus, sentinel = _mk_sentinel()
    sentinel.check_once()  # 建基线
    store.set_price("iPhone 15", 5999 * 1.03)  # 恰好 +3%
    alerts = sentinel.check_once()
    assert any(a["product"] == "iPhone 15" and a["type"] == "price" for a in alerts)


def test_price_change_2_99pct_silent():
    store, bus, sentinel = _mk_sentinel()
    sentinel.check_once()
    store.set_price("小米14", 3999 * 1.0299)
    alerts = sentinel.check_once()
    assert not any(a["product"] == "小米14" for a in alerts)


def test_negative_rate_exactly_5pct_alerts():
    store, bus, sentinel = _mk_sentinel()
    sentinel.check_once()
    base = store.get("华为Mate60")["negative_rate"]
    # +5.01pp 确保越过 5% 阈值 (避开浮点误差临界)
    store.set_negative_rate("华为Mate60", base + 0.0501)
    alerts = sentinel.check_once()
    assert any(a["type"] == "negative_review" and a["product"] == "华为Mate60" for a in alerts)


def test_negative_rate_improvement_never_alerts():
    store, bus, sentinel = _mk_sentinel()
    sentinel.check_once()
    base = store.get("三星S24")["negative_rate"]
    store.set_negative_rate("三星S24", max(0.0, base - 0.08))  # 差评率下降
    alerts = sentinel.check_once()
    assert alerts == []


# ---------- 优化器极端输入 ----------
def test_zero_inventory_all_shortage_rush_fee():
    r = estimate_profit(99, 0, 0, 105)
    assert r["shortage"] == r["demand"] > 0
    # profit_model 所有字段 round(2): rush_cost 在 round 前按精确缺口计算,
    # 用 round 后的 shortage 反乘会有 <=0.08 的舍入差, 给容差
    assert r["rush_cost"] == pytest.approx(
        r["shortage"] * OPTIMIZER_CONFIG["rush_fee_per_unit"], abs=0.5)


def test_zero_budget_lift_is_one():
    with_budget = estimate_profit(99, 5000, 300, 105)
    no_budget = estimate_profit(99, 0, 300, 105)
    assert with_budget["demand"] > no_budget["demand"]  # 广告有增益
    assert no_budget["ad_cost"] == 0


def test_extreme_high_price_kills_demand():
    r = estimate_profit(10000, 0, 300, 105)  # 价格是竞品 95 倍
    assert r["demand"] == 0
    assert r["GMV"] == 0
    assert r["profit"] < 0  # 仍亏仓储与广告


def test_solver_all_candidates_loss_picks_least_bad():
    ctx = {"competitor_price": 105, "inventory": 300, "base_sales": 1, "elastic": 1.5}
    cands = [{"price": 900, "ad_budget": 9000}, {"price": 800, "ad_budget": 9500}]
    res = solve(cands, ctx, n_sims=200, seed=1)
    assert res["best"]["mean_profit"] < 0
    assert res["best"]["mean_profit"] >= res["ranking"][-1]["mean_profit"]


# ---------- 执行器异常输入 ----------
def _mk_verifier():
    store = MockStoreAPI()
    rb = RollbackManager(store_api=store, auto_start=False)
    ap = ApprovalManager()
    return store, rb, ap, ActionVerifier(store_api=store, rollback_manager=rb, approvals=ap)


def test_zero_price_rejected_no_rollback_record():
    store, rb, ap, verifier = _mk_verifier()
    # 直接走内部执行路径模拟批准后执行
    receipt = verifier._execute("update_price", {"product_id": "default_hot_item", "new_price": 0})
    assert receipt["success"] is False
    assert store.get_price("default_hot_item") == 99.0
    assert rb.pending_ids() == []


def test_unsupported_action_marked_failed():
    store, rb, ap, verifier = _mk_verifier()
    receipt = verifier._execute("launch_rocket", {})
    assert receipt["success"] is False
    assert receipt["post_status"] == "failed"


def test_confirmed_action_cannot_rollback():
    store, rb, ap, verifier = _mk_verifier()
    receipt = verifier._execute("update_price", {"product_id": "default_hot_item", "new_price": 88})
    assert receipt["success"] is True
    assert rb.confirm(receipt["action_id"]) is True
    res = rb.rollback(receipt["action_id"])
    assert res["success"] is False and res["reason"] == "already_confirmed"


def test_get_store_api_singleton_mock():
    a, b = get_store_api(), get_store_api()
    assert a is b
    assert a.platform == "mock"
    assert EXECUTOR_REAL_MODE is False


# ---------- 仲裁边界 ----------
def test_two_goals_do_not_trigger():
    assert is_conflicted(detect_conflicts("保利润 + 冲量")) is False


def test_four_goals_all_trigger():
    goals = detect_conflicts("保利润，冲量，省预算，还要清库存")
    assert len(goals) == 4
    resolver = ConflictResolver()
    result = resolver.resolve("保利润，冲量，省预算，还要清库存")
    assert result["type"] == "conflict_decision"
    assert len(result["data"]["goals"]) == 4


def test_empty_input_no_conflict():
    resolver = ConflictResolver()
    assert resolver.resolve("")["type"] == "no_conflict"


# ---------- 事件总线边界 ----------
def test_publish_with_zero_subscribers_returns_zero():
    bus = EventBus()
    assert bus.publish(MARKET_ALERT, {"x": 1}) == 0


def test_history_records_all_events():
    bus = EventBus()
    for i in range(5):
        bus.publish(MARKET_ALERT, {"i": i})
    hist = bus.get_history()
    assert len(hist) == 5
    assert hist[-1]["data"]["i"] == 4
