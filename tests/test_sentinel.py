"""任务9 市场哨兵测试: 模拟价格波动, 验证 MARKET_ALERT 事件触发"""
from app.sentinel.event_bus import EventBus, MARKET_ALERT, INVENTORY_LOW
from app.sentinel.crawler_base import MockMarketStore, MockTmallCrawler
from app.sentinel.trigger_engine import MarketSentinel


def _make_sentinel():
    store = MockMarketStore()
    crawler = MockTmallCrawler(store=store)
    bus = EventBus()
    return MarketSentinel(crawler=crawler, bus=bus, store=store), store, bus


def test_event_bus_pubsub():
    bus = EventBus()
    received = []
    bus.subscribe(INVENTORY_LOW, lambda e: received.append(e))
    delivered = bus.publish(INVENTORY_LOW, {"sku": "SKU001", "inventory": 5})
    assert delivered == 1
    assert received[0]["data"]["sku"] == "SKU001"
    assert len(bus.get_history(INVENTORY_LOW)) == 1


def test_event_bus_handler_error_isolation():
    bus = EventBus()
    ok = []
    bus.subscribe(MARKET_ALERT, lambda e: 1 / 0)
    bus.subscribe(MARKET_ALERT, lambda e: ok.append(1))
    bus.publish(MARKET_ALERT, {"x": 1})
    assert ok == [1]  # 单个 handler 异常不影响其他订阅者


def test_event_bus_unsubscribe():
    bus = EventBus()
    received = []
    handler = lambda e: received.append(e)  # noqa: E731
    bus.subscribe(MARKET_ALERT, handler)
    bus.unsubscribe(MARKET_ALERT, handler)
    bus.publish(MARKET_ALERT, {"x": 1})
    assert received == []


def test_first_check_builds_baseline_no_alert():
    sentinel, store, bus = _make_sentinel()
    received = []
    bus.subscribe(MARKET_ALERT, lambda e: received.append(e))
    alerts = sentinel.check_once()
    assert alerts == []
    assert "iPhone 15" in sentinel.baseline
    assert received == []


def test_price_drop_4pct_triggers_alert():
    """Checkpoint 1: 竞品 iPhone 15 降价 4% 应触发 MARKET_ALERT"""
    sentinel, store, bus = _make_sentinel()
    received = []
    bus.subscribe(MARKET_ALERT, lambda e: received.append(e))

    sentinel.check_once()  # 建立基线
    store.set_price("iPhone 15", 5999.0 * 0.96)  # 降价 4%
    alerts = sentinel.check_once()

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["type"] == "price"
    assert alert["product"] == "iPhone 15"
    assert abs(alert["change_pct"] - (-0.04)) < 1e-6
    assert alert["message"] == "[ALERT] 竞品 iPhone 15 降价 4%"
    print(alert["message"])  # Checkpoint 1: 终端可见

    assert len(received) == 1
    assert received[0]["data"]["message"] == alert["message"]


def test_small_fluctuation_no_alert():
    sentinel, store, bus = _make_sentinel()
    received = []
    bus.subscribe(MARKET_ALERT, lambda e: received.append(e))
    sentinel.check_once()
    store.set_price("小米14", 3999.0 * 0.98)  # 2% < 3% 阈值
    alerts = sentinel.check_once()
    assert alerts == []
    assert received == []


def test_price_increase_triggers_alert():
    sentinel, store, bus = _make_sentinel()
    sentinel.check_once()
    store.set_price("三星S24", 4999.0 * 1.05)  # 涨价 5%
    alerts = sentinel.check_once()
    assert len(alerts) == 1
    assert alerts[0]["change_pct"] > 0
    assert "涨价" in alerts[0]["message"]


def test_negative_review_spike_triggers_alert():
    sentinel, store, bus = _make_sentinel()
    received = []
    bus.subscribe(MARKET_ALERT, lambda e: received.append(e))
    sentinel.check_once()
    store.set_negative_rate("荣耀Magic6", 0.04 + 0.06)  # 差评率突增 6%
    alerts = sentinel.check_once()
    assert len(alerts) == 1
    assert alerts[0]["type"] == "negative_review"
    assert alerts[0]["change"] >= 0.05
    assert len(received) == 1


def test_top_n_limit():
    store = MockMarketStore()
    assert len(store.top_products(10)) == 10
    assert len(store.top_products(3)) == 3
