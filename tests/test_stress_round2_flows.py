# -*- coding: utf-8 -*-
"""s10 第 2 轮压测: 端到端组合链路 (用例与既有测试/第 1 轮完全不重复)"""
from fastapi.testclient import TestClient

import app.executor.action_verifier as av_mod
from app.agent.workflow import skill_executor
from app.optimizer.conflict_resolver import ConflictResolver
from app.sentinel.crawler_base import MockMarketStore, MockTmallCrawler
from app.sentinel.event_bus import EventBus, MARKET_ALERT
from app.sentinel.trigger_engine import MarketSentinel
from app.skills.pricing_skill import pricing_skill
from app.utils.approval import ApprovalManager


# ---------- 仲裁 -> 点选 B -> 批准 -> Mock 执行 -> 确认不回滚 ----------
def test_conflict_choice_b_full_lifecycle():
    resolver = ConflictResolver()
    result = resolver.resolve("保利润 + 冲量 + 清库存，我要一个稳妥方案")
    rid = result["data"]["resolver_id"]
    plan_b = result["data"]["options"]["B"]

    verify = resolver.apply_choice(rid, "B", conversation_id="conv-round2")
    assert verify["type"] == "approval_required"
    from app.utils.approval import approval_manager
    aid = verify["data"]["approval_id"]
    approval_manager.resolve(aid, True)
    receipt = approval_manager.take_and_execute(aid)

    assert receipt["success"] is True
    verifier = av_mod.get_action_verifier()
    assert verifier.store.get_price("default_hot_item") == plan_b["price"]
    # 回滚窗口登记 + 人工确认 + 超期巡检不回滚
    action_id = receipt["action_id"]
    assert verifier.rollback.confirm(action_id) is True
    verifier.rollback.confirm_window = 0.0  # 极端: 立即超期
    rolled = verifier.rollback.sweep_once()
    assert action_id not in rolled  # 已确认的动作绝不回滚 (其余待确认动作可能被扫到, 不影响本断言)
    assert verifier.store.get_price("default_hot_item") == plan_b["price"]
    verifier.rollback.confirm_window = 3600  # 还原


# ---------- 哨兵三步曲: 基线 -> 静默 -> 告警 -> 基线漂移 ----------
def test_sentinel_baseline_drift_lifecycle():
    store = MockMarketStore()
    bus = EventBus()
    sentinel = MarketSentinel(crawler=MockTmallCrawler(store=store), bus=bus, store=store)

    assert sentinel.check_once() == []          # 第 1 次建基线
    assert sentinel.check_once() == []          # 第 2 次无波动静默
    store.set_price("OPPO Find X7", 4299 * 0.95)  # 降价 5%
    alerts = sentinel.check_once()
    assert any(a["product"] == "OPPO Find X7" for a in alerts)
    hist = bus.get_history()
    # 事件结构为 {"type", "data", "timestamp"}
    assert any(e["type"] == MARKET_ALERT and e["data"]["product"] == "OPPO Find X7"
               for e in hist)
    # 基线已漂移: 维持新价再巡检应静默
    assert sentinel.check_once() == []


# ---------- pricing_skill 纯上下文信息(无指令) -> 不触发改价 -> 价格不变 ----------
def test_pricing_skill_custom_context_rejected():
    verifier = av_mod.get_action_verifier()
    verifier.store._prices["default_hot_item"] = 120.0
    result = pricing_skill("当前售价 120，竞品均价 110，库存量 400，广告预算 1000")
    # 只给了上下文、没有明示调价指令: 只出建议, 不产生执行请求(问价≠调价)
    assert result["is_executable"] is False
    assert result["execution_request"] is None
    assert verifier.store.get_price("default_hot_item") == 120.0  # 价格保持不变


# ---------- HTTP 端点组合: sentinel/check -> 执行回执查询链路 ----------
def test_http_sentinel_and_executor_status_combo():
    import app.main as main_mod
    # 适配 fail-closed 鉴权: 测试环境注入 API Key
    main_mod._API_KEY = "test-key"
    client = TestClient(main_mod.app)
    client.headers.update({"X-API-Key": "test-key"})

    r1 = client.post("/sentinel/check")
    assert r1.status_code == 200
    body = r1.json()
    assert body["status"] == "ok"
    assert isinstance(body["alerts"], list)

    # 通过仲裁链路产生一个真实 action_id, 再查状态与确认
    resolver = ConflictResolver()
    dec = resolver.resolve("省预算 + 保销量 + 清库存")
    rid = dec["data"]["resolver_id"]
    verify = resolver.apply_choice(rid, "A")
    from app.utils.approval import approval_manager
    aid = verify["data"]["approval_id"]
    approval_manager.resolve(aid, True)
    receipt = approval_manager.take_and_execute(aid)
    action_id = receipt["action_id"]

    r2 = client.get("/executor/status/%s" % action_id)
    assert r2.status_code == 200
    assert r2.json()["entry"]["status"] == "awaiting_confirmation"

    r3 = client.post("/executor/confirm/%s" % action_id)
    assert r3.json()["confirmed"] is True
    r4 = client.get("/executor/status/%s" % action_id)
    assert r4.json()["entry"]["status"] == "confirmed"


# ---------- workflow 级冲突路由 -> 点选 -> 批准 -> Mock 执行 ----------
def test_workflow_conflict_route_to_mock_execution(capsys):
    state = {
        # GOAL_KEYWORDS 为精确子串匹配: 必须含 "省预算/销量/清库存" 标准关键词才能凑满 3 目标
        "tool_result": {"user_input": "帮我省预算，销量要保住，还要清库存"},
        "conversation_id": "conv-r2-wf",
    }
    out = skill_executor(state)
    assert out["tool_result"]["type"] == "conflict_decision"
    rid = out["tool_result"]["data"]["resolver_id"]

    from app.optimizer.conflict_resolver import get_conflict_resolver
    verify = get_conflict_resolver().apply_choice(rid, "A")
    assert verify["type"] == "approval_required"

    from app.utils.approval import approval_manager
    aid = verify["data"]["approval_id"]
    approval_manager.resolve(aid, True)
    receipt = approval_manager.take_and_execute(aid)
    assert receipt["success"] is True
    out_text = capsys.readouterr().out
    assert "模拟修改价格成功" in out_text
    assert "Mock 执行成功" in out_text
