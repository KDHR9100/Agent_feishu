# -*- coding: utf-8 -*-
"""s10 第 3 轮压测: 并发健壮性 + 老功能回归 + Checkpoint 复验 (用例不重复)"""
import threading

import pytest
from fastapi.testclient import TestClient

from app.agent.workflow import EXECUTABLE_SKILLS, SKILL_REGISTRY
from app.config import EXECUTOR_REAL_MODE, OPTIMIZER_CONFIG, SENTINEL_CONFIG
from app.executor.platform_adapter import get_store_api
from app.executor.rollback_manager import RollbackManager
from app.sentinel.event_bus import EventBus, MARKET_ALERT
from app.executor.platform_adapter import MockStoreAPI


# ---------- 并发: 事件总线 ----------
def test_event_bus_concurrent_publish_subscribe():
    # max_history=500 让 400 条事件全部留痕 (默认 200 会截断)
    bus = EventBus(max_history=500)
    received = []
    lock = threading.Lock()

    def make_handler():
        # EventBus.subscribe 对同一 handler 对象去重, 故构造 3 个独立闭包验证扇出
        def handler(event):
            with lock:
                received.append(event["data"]["i"])
        return handler

    for _ in range(3):
        bus.subscribe(MARKET_ALERT, make_handler())

    def publisher(tid):
        for i in range(50):
            bus.publish(MARKET_ALERT, {"i": tid * 100 + i})

    threads = [threading.Thread(target=publisher, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(received) == 8 * 50 * 3  # 8 发布者 x 50 事件 x 3 订阅者
    assert len(bus.get_history()) == 400

    # 同一 handler 重复订阅只生效一次 (去重语义)
    bus2 = EventBus()
    counter = []
    same_handler = lambda e: counter.append(1)  # noqa: E731
    bus2.subscribe(MARKET_ALERT, same_handler)
    bus2.subscribe(MARKET_ALERT, same_handler)
    bus2.publish(MARKET_ALERT, {})
    assert len(counter) == 1


def test_event_bus_handler_exception_isolated_under_concurrency():
    bus = EventBus()
    ok = []

    bus.subscribe(MARKET_ALERT, lambda e: (_ for _ in ()).throw(ValueError("boom")))
    bus.subscribe(MARKET_ALERT, lambda e: ok.append(1))

    threads = [threading.Thread(target=lambda: bus.publish(MARKET_ALERT, {}))
               for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ok) == 20  # 坏 handler 不影响好 handler 与并发发布


# ---------- 并发: 回滚管理器 ----------
def test_rollback_manager_concurrent_record_confirm_sweep():
    store = MockStoreAPI()
    rb = RollbackManager(store_api=store, confirm_window_seconds=0.02, auto_start=False)
    ids = []
    lock = threading.Lock()

    def recorder():
        for _ in range(20):
            aid = rb.record("update_price", {"product_id": "default_hot_item", "new_price": 90},
                            {"old_price": 99.0})
            with lock:
                ids.append(aid)

    threads = [threading.Thread(target=recorder) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ids) == 80 and len(set(ids)) == 80  # action_id 全局唯一

    # 一半确认, 一半等超期
    for aid in ids[:40]:
        assert rb.confirm(aid) is True

    import time
    time.sleep(0.05)
    rolled = rb.sweep_once()
    assert set(rolled) == set(ids[40:])  # 只有未确认的被回滚


# ---------- 并发: MockStoreAPI 写入冒烟 ----------
def test_mock_store_concurrent_price_updates_no_crash():
    store = MockStoreAPI()
    def updater(n):
        for i in range(100):
            store.update_price("item_%d" % n, 10.0 + i)
    threads = [threading.Thread(target=updater, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for n in range(6):
        assert store.get_price("item_%d" % n) == pytest.approx(109.0)


# ---------- 回归: 12 老技能注册机制未被破坏 ----------
LEGACY_SKILLS = [
    "product_skill", "ads_skill", "content_skill", "help_skill",
    "file_analysis_skill", "inventory_skill", "competitor_skill",
    "report_skill", "rag_skill", "seo_skill", "support_skill",
    "data_analysis_skill",
]


def test_legacy_12_skills_registry_intact():
    for s in LEGACY_SKILLS:
        assert s in SKILL_REGISTRY and callable(SKILL_REGISTRY[s])
    assert "pricing_skill" in SKILL_REGISTRY  # 新增技能并列挂载
    assert "pricing_skill" in EXECUTABLE_SKILLS


def test_router_keyword_rules_include_pricing_and_legacy():
    from app.agent.router import KEYWORD_RULES, keyword_fallback
    assert "定价" in KEYWORD_RULES["pricing_skill"]
    assert "中秋活动价" in KEYWORD_RULES["pricing_skill"]
    # 老技能关键词路由不受影响
    assert keyword_fallback("帮我分析一下商品销量") == ["product_skill"]
    assert keyword_fallback("广告投放ROI怎么样") == ["ads_skill"]
    # 新技能关键词路由生效
    assert keyword_fallback("怎么定中秋活动价") == ["pricing_skill"]


# ---------- 回归: 配置约束 ----------
def test_config_hard_constraints():
    assert EXECUTOR_REAL_MODE is False  # 默认严禁真实操作
    required_keys = [
        "price_elasticity", "base_sales", "unit_cost", "storage_fee_rate",
        "rush_fee_per_unit", "ad_effectiveness", "mc_simulations",
        "demand_noise_std", "competitor_price_noise_std",
    ]
    for k in required_keys:
        assert k in OPTIMIZER_CONFIG
    assert OPTIMIZER_CONFIG["mc_simulations"] == 1000
    assert SENTINEL_CONFIG["poll_interval_minutes"] == 30
    assert SENTINEL_CONFIG["price_change_threshold"] == 0.03
    assert SENTINEL_CONFIG["negative_review_threshold"] == 0.05


# ---------- Checkpoint 复验 (脚本化) ----------
def test_checkpoint1_alert_message_format(capsys):
    from app.sentinel.crawler_base import MockMarketStore, MockTmallCrawler
    from app.sentinel.trigger_engine import MarketSentinel
    store = MockMarketStore()
    sentinel = MarketSentinel(crawler=MockTmallCrawler(store=store),
                              bus=EventBus(), store=store)
    sentinel.check_once()
    store.set_price("iPhone 15", 5999 * 0.96)  # 降价 4%
    sentinel.check_once()
    out = capsys.readouterr().out
    assert "[ALERT] 竞品 iPhone 15 降价 4%" in out


def test_checkpoint2_endpoint_json_shape():
    import app.main as main_mod
    client = TestClient(main_mod.app)
    body = client.post("/optimize/pricing", json={"seed": 77}).json()
    for field in ["recommended_price", "confidence_interval", "simulations",
                  "loss_probability", "roi_lift_pct", "ranking"]:
        assert field in body
    assert body["simulations"] == 1000
    assert body["confidence_interval"]["level"] == "95%"


def test_checkpoint3_approval_gate_then_mock(capsys):
    from app.agent.workflow import _execute_single_skill
    from app.utils.approval import approval_manager
    result = _execute_single_skill(
        "pricing_skill", "帮我把爆款涨价 10%（当前售价 99，竞品均价 105）",
        None, None, {}, {"conversation_id": "conv-r3"})
    assert result["type"] == "approval_required"  # 不直接执行
    aid = result["data"]["approval_id"]
    approval_manager.resolve(aid, True)
    receipt = approval_manager.take_and_execute(aid)
    assert receipt["success"] is True
    out = capsys.readouterr().out
    assert "Mock 执行成功" in out
