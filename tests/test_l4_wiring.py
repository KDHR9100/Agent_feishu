# -*- coding: utf-8 -*-
"""s8 总装测试: skill_executor 冲突仲裁路由 + L4 HTTP 端点 (FastAPI app 级)"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    # 不使用 with 上下文, 避免触发 startup 事件 (哨兵/WS 客户端)
    import app.main as main_mod
    # 适配 fail-closed 鉴权: 测试环境注入 API Key
    main_mod._API_KEY = "test-key"
    client = TestClient(main_mod.app)
    client.headers.update({"X-API-Key": "test-key"})
    return client


# ---------- skill_executor 冲突仲裁路由 ----------
def test_skill_executor_routes_conflict_to_resolver():
    from app.agent.workflow import skill_executor
    state = {
        "tool_result": {"user_input": "省预算 + 保销量 + 清库存，帮我权衡一下"},
        "conversation_id": "conv-conflict-e2e",
    }
    out = skill_executor(state)
    tr = out["tool_result"]
    assert tr["type"] == "conflict_decision"
    assert out["skill_results"][0]["skill"] == "conflict_resolver"
    assert set(tr["data"]["options"].keys()) == {"A", "B"}
    # 决策看板卡片内嵌点选按钮
    buttons = tr["data"]["card"]["elements"][-1]["actions"]
    assert buttons[0]["value"]["action"] == "choose_option"


def test_skill_executor_non_conflict_not_short_circuited():
    """单目标请求不应触发仲裁短路 (detect 层拦截)"""
    from app.optimizer.conflict_resolver import detect_conflicts, is_conflicted
    assert is_conflicted(detect_conflicts("帮我分析一下商品销量")) is False


# ---------- HTTP 端点 ----------
def test_pricing_endpoint_on_real_app(client):
    r = client.post("/optimize/pricing", json={"seed": 11})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["confidence_interval"]["lower"] <= body["expected_profit"] <= body["confidence_interval"]["upper"]


def test_resolve_conflict_endpoint(client):
    r = client.post("/optimize/resolve-conflict", json={
        "user_input": "我要保利润，也要冲量，还要清库存",
        "conversation_id": "conv-http-e2e",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "conflict_decision"
    assert body["data"]["resolver_id"]


def test_resolve_conflict_no_conflict(client):
    r = client.post("/optimize/resolve-conflict", json={"user_input": "看看销量"})
    assert r.json()["type"] == "no_conflict"


def test_choose_option_endpoint_full_flow(client):
    """HTTP 侧点选闭环: resolve -> choose -> approval_required"""
    r1 = client.post("/optimize/resolve-conflict", json={
        "user_input": "省预算 + 保销量 + 清库存", "conversation_id": "conv-http-choice"})
    rid = r1.json()["data"]["resolver_id"]
    r2 = client.post("/optimize/choose-option", json={"resolver_id": rid, "choice": "A"})
    body = r2.json()
    assert body["type"] == "approval_required"
    assert body["data"]["approval_id"]
    # 重复点选同一会话应失败 (一次性消费)
    r3 = client.post("/optimize/choose-option", json={"resolver_id": rid, "choice": "A"})
    assert r3.json()["type"] == "error"


def test_sentinel_check_endpoint(client):
    r = client.post("/sentinel/check")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "alerts" in body and "sentinel_status" in body


def test_executor_confirm_and_status_endpoints(client):
    r = client.post("/executor/confirm/nonexistent-id")
    assert r.status_code == 200
    assert r.json()["confirmed"] is False

    r2 = client.get("/executor/status/nonexistent-id")
    assert r2.status_code == 404
