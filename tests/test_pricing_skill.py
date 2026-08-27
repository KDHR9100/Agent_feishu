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


def test_pricing_consultation_not_executable():
    """'帮我定价' 是咨询问句: 只给建议, 绝不生成改价执行请求(问价≠调价)"""
    result = pricing_skill("当前售价 99，竞品均价 105，帮我定价")
    assert result["is_executable"] is False
    assert result["execution_request"] is None
    text = result["data"]["analysis"]
    assert "咨询模式" in text or "建议模式" in text
    assert "未发起任何调价操作" in text


def test_pricing_explicit_directive_execution_request():
    """明示调价指令(目标价): 才可执行, 生成 update_price 请求"""
    result = pricing_skill("当前售价 99，竞品均价 105，调价到 89")
    assert result["is_executable"] is True
    req = result["execution_request"]
    assert req["action"] == "update_price"
    assert req["params"]["old_price"] == 99.0
    assert req["params"]["new_price"] == 89.0
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


def test_target_price_override():
    """用户明示目标价(如 降到 101)时, execution_request 以目标价为准而非沙盒最优价"""
    from app.executor.platform_adapter import get_store_api
    from app.skills.pricing_skill import pricing_skill
    # 构造真降价语境: 店铺实时价 110 -> 用户要求降到 101
    get_store_api().update_price("default_hot_item", 110.0)
    try:
        result = pricing_skill("帮我把爆款价格降到 101")
    finally:
        get_store_api().update_price("default_hot_item", 99.0)  # 还原, 避免污染其他用例
    params = result["execution_request"]["params"]
    assert params["new_price"] == 101.0
    assert params["old_price"] == 110.0
    assert "降价" in result["execution_request"]["description"]
    assert "按您的指示" in result["data"]["analysis"]


def test_no_directive_stays_advice_mode():
    """未明示调价指令时: 只输出沙盒测算建议, 不产生任何执行请求"""
    from app.skills.pricing_skill import pricing_skill
    result = pricing_skill("帮我定个价")
    assert result["is_executable"] is False
    assert result["execution_request"] is None
    assert "按您的指示" not in result["data"]["analysis"]


def test_directive_percent_up():
    """明示 '涨 10%': 按指令执行(基于店铺实时价), 不用 AI 最优价"""
    from app.executor.platform_adapter import get_store_api
    from app.skills.pricing_skill import pricing_skill
    get_store_api().update_price("default_hot_item", 100.0)
    try:
        result = pricing_skill("帮我把爆款价格涨 10%")
    finally:
        get_store_api().update_price("default_hot_item", 99.0)
    params = result["execution_request"]["params"]
    assert params["new_price"] == 110.0
    assert params["old_price"] == 100.0
    assert "涨价" in result["execution_request"]["description"]
    assert "按您的指示" in result["data"]["analysis"]


def test_directive_percent_down():
    """明示 '降价 5%': 按指令降价"""
    from app.executor.platform_adapter import get_store_api
    from app.skills.pricing_skill import pricing_skill
    get_store_api().update_price("default_hot_item", 100.0)
    try:
        result = pricing_skill("爆款降价 5% 吧")
    finally:
        get_store_api().update_price("default_hot_item", 99.0)
    params = result["execution_request"]["params"]
    assert params["new_price"] == 95.0
    assert "降价" in result["execution_request"]["description"]


def test_directive_money_amount():
    """明示 '加 20 元' / '便宜 10 块': 按金额调整"""
    from app.executor.platform_adapter import get_store_api
    from app.skills.pricing_skill import pricing_skill
    get_store_api().update_price("default_hot_item", 100.0)
    try:
        r_up = pricing_skill("价格加 20 元")
        assert r_up["execution_request"]["params"]["new_price"] == 120.0
        r_down = pricing_skill("便宜 10 块")
        assert r_down["execution_request"]["params"]["new_price"] == 90.0
    finally:
        get_store_api().update_price("default_hot_item", 99.0)


def test_directive_target_price_beats_percent():
    """同时含目标价与百分比时, 目标价(到 X)优先"""
    from app.executor.platform_adapter import get_store_api
    from app.skills.pricing_skill import pricing_skill
    get_store_api().update_price("default_hot_item", 100.0)
    try:
        result = pricing_skill("涨 10%，最终调到 115")
    finally:
        get_store_api().update_price("default_hot_item", 99.0)
    assert result["execution_request"]["params"]["new_price"] == 115.0


def test_competitor_mention_not_a_directive():
    """'竞品降价了 4%' 是市场描述不是指令, 不触发明示执行"""
    from app.skills.pricing_skill import _parse_directive
    assert _parse_directive("竞品降价了 4%，我们怎么办", 100.0) is None


def test_parse_context_uses_real_db_data_for_sku():
    """P8: 指定 SKU 时, 现价/库存必须取库内真实数据, 不得回退配置默认值"""
    ctx = parse_context("把 SKU001 降到 80 元")
    assert ctx["inventory"] == 50.0      # conftest 测试数据: SKU001 inventory=50
    assert ctx["current_price"] == 99.0  # conftest 测试数据: SKU001 avg_price=99.0
    assert ctx["_sku_in_db"] is True
    assert ctx["_sources"]["inventory"] == "库内真实数据"
    assert ctx["_sources"]["current_price"] == "库内真实数据"
    assert ctx["_sources"]["competitor_price"] == "示例基准"  # 库内无竞品数据


def test_render_labels_data_sources():
    """P8: 【上下文】行逐项标注来源 —— 真实数据照实展示, 默认值标注'示例基准'"""
    result = pricing_skill("把 SKU001 降到 80 元")
    text = result["data"]["analysis"]
    assert "库存 50 件（库内真实数据）" in text
    assert "示例基准，非真实数据" in text


def test_unknown_sku_falls_back_to_sample_labels():
    """库中不存在的 SKU 回退示例基准值, 且必须如实标注, 不冒充真实数据"""
    ctx = parse_context("把 SKU_NOT_EXIST_XYZ 降到 80 元")
    assert ctx["_sku_in_db"] is False
    assert ctx["_sources"]["inventory"] == "示例基准"
    assert ctx["_sources"]["current_price"] != "库内真实数据"
