# -*- coding: utf-8 -*-
"""s4 定价技能 + /optimize/pricing 接口测试"""
from fastapi import FastAPI, APIRouter  # noqa: F401
from fastapi.testclient import TestClient

from app.skills.pricing_skill import (
    build_candidates,
    optimize_pricing,
    parse_context,
    pricing_skill,
)
from app.config import OPTIMIZER_CONFIG


def test_parse_context_with_numbers():
    ctx = parse_context("当前售价 88 元，竞品均价 95，库存量 500，广告预算 1200")
    assert ctx["current_price"] == 88.0
    assert ctx["competitor_price"] == 95.0
    assert ctx["inventory"] == 500.0
    assert ctx["ad_budget"] == 1200.0


def test_parse_context_fallback_defaults():
    ctx = parse_context("怎么定中秋活动价")
    assert ctx["current_price"] == OPTIMIZER_CONFIG["default_price"]
    assert ctx["competitor_price"] == OPTIMIZER_CONFIG["default_competitor_price"]


def test_build_candidates_five_around_current():
    cands = build_candidates(100.0, 800.0)
    assert len(cands) == 5
    prices = [c["price"] for c in cands]
    assert 100.0 in prices  # 含现状基线
    assert min(prices) < 100.0 < max(prices)  # 覆盖降价与涨价两侧


def test_pricing_skill_output_format():
    result = pricing_skill("帮我看看中秋活动价怎么定")
    assert result["type"] == "analysis"
    text = result["data"]["analysis"]
    assert "建议" in text
    assert "置信区间" in text
    assert "ROI" in text
    assert "蒙特卡洛" in text


def test_pricing_skill_execution_request():
    result = pricing_skill("当前售价 99，竞品均价 105，帮我定价")
    assert result["is_executable"] is True
    req = result["execution_request"]
    assert req["action"] == "update_price"
    assert req["params"]["old_price"] == 99.0
    assert req["params"]["new_price"] > 0
    assert "description" in req


def test_optimize_best_not_worse_than_baseline():
    """最优方案的期望利润必须 >= 维持现状基线 (C3) 方案"""
    ctx = parse_context("当前售价 99，竞品均价 105")
    opt = optimize_pricing(ctx, seed=42)
    baseline = next(
        r for r in opt["ranking"]
        if r["candidate"]["price"] == ctx["current_price"]
    )
    assert opt["best"]["mean_profit"] >= baseline["mean_profit"]


def test_optimize_reproducible_with_seed():
    ctx = parse_context("")
    a = optimize_pricing(ctx, seed=7)
    b = optimize_pricing(ctx, seed=7)
    assert a["best"]["mean_profit"] == b["best"]["mean_profit"]


def test_confidence_interval_brackets_mean():
    ctx = parse_context("")
    opt = optimize_pricing(ctx, seed=1)
    best = opt["best"]
    assert best["ci_lower"] <= best["mean_profit"] <= best["ci_upper"]


def _make_client():
    from app.optimizer.api import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_optimize_pricing_endpoint_default_params():
    """Checkpoint 2 核心: POST /optimize/pricing 返回带置信区间的 JSON"""
    client = _make_client()
    resp = client.post("/optimize/pricing", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["recommended_price"] > 0
    ci = body["confidence_interval"]
    assert ci["level"] == "95%"
    assert ci["lower"] <= body["expected_profit"] <= ci["upper"]
    assert body["simulations"] == OPTIMIZER_CONFIG["mc_simulations"]
    assert len(body["ranking"]) == 5
    assert "loss_probability" in body


def test_optimize_pricing_endpoint_custom_params():
    client = _make_client()
    resp = client.post("/optimize/pricing", json={
        "current_price": 120, "competitor_price": 110,
        "inventory": 400, "ad_budget": 1000, "n_sims": 300, "seed": 3,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["context"]["current_price"] == 120
    assert body["simulations"] == 300
    assert body["confidence_interval"]["lower"] <= body["expected_profit"]


def test_endpoint_change_pct_consistency():
    client = _make_client()
    resp = client.post("/optimize/pricing", json={"seed": 5})
    body = resp.json()
    expected = (body["recommended_price"] - body["context"]["current_price"]) \
        / body["context"]["current_price"] * 100.0
    assert abs(body["change_pct"] - expected) < 0.01
