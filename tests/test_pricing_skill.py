# -*- coding: utf-8 -*-
"""s4 定价技能 + /optimize/pricing 接口测试"""
from fastapi import FastAPI, APIRouter  # noqa: F401
from fastapi.testclient import TestClient

from app.skills.pricing_skill import (
    _last_sku_from_history,
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


def test_pricing_advice_carries_sku_anchor():
    """带 SKU 的咨询：回答必须携带 SKU 标识（多轮指代锚点）。

    评测一致性探针实测（run-20260910-132010 缺陷档案 #4）：建议模式模板
    不含 SKU，后续轮"还是那个 SKU"的回答失去指代锚点。
    """
    result = pricing_skill("SKU-PX01 双 11 活动价怎么定")
    text = result["data"]["analysis"]
    assert "SKU-PX01" in text


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


# ============================================================
# 缺陷档案 #2/#4 第二轮: 建议模式会话感知
# (run-20260910-140936: pricing_analyst 5 轮要不到敏感性、追问轮失忆话术)
# ============================================================

_HISTORY_WITH_ADVICE = [
    {"role": "user", "content": "SKU001 双11活动价怎么定"},
    {"role": "assistant",
     "content": "【建议模式】…📊 损益优化沙盒定价建议（SKU001，1000 次蒙特卡洛模拟）…"},
]


def test_session_sku_memory_on_followup():
    """追问轮不再复述 SKU 时, 上下文应锚定会话内最近讨论的商品

    评测一致性维失败实录: turn 2 无 SKU 的追问触发"未识别到具体商品"
    失忆话术 + 回退默认基准商品。
    """
    ctx = parse_context("弹性假设会不会把结论带偏",
                        product_id=_last_sku_from_history(_HISTORY_WITH_ADVICE))
    assert ctx["_product_id"] == "SKU001"
    assert ctx["_sources"]["current_price"] == "库内真实数据"  # 锚定 SKU001 的真实价


def test_followup_supplement_instead_of_template_repeat():
    """已发过完整建议 + 本轮纯追问(无新参数无指令): 只补充回应, 不重发整块模板"""
    result = pricing_skill("95%置信区间到底给不给，弹性假设会不会把结论带偏",
                           history=_HISTORY_WITH_ADVICE)
    text = result["data"]["analysis"]
    assert result["is_executable"] is False
    assert "补充说明" in text and "不再重发完整建议" in text
    assert "损益优化沙盒定价建议（" not in text   # 不重发完整模板
    assert "95% 置信区间" in text                  # 逐点回应置信区间
    assert "价格弹性" in text                      # 逐点回应弹性假设
    assert "SKU001" in text                        # 会话 SKU 锚定


def test_followup_with_new_numbers_still_full_render():
    """追问带新参数("用 118.6 和 1520 重跑"): 用户要的是重跑, 应重发完整测算"""
    result = pricing_skill("用 99 和 50 重跑95%置信区间与敏感性",
                           history=_HISTORY_WITH_ADVICE)
    text = result["data"]["analysis"]
    assert "损益优化沙盒定价建议" in text
    assert "【敏感性】" in text                     # 敏感性关键词触发小节


def test_sensitivity_section_on_first_request():
    """首轮即要求敏感性: 完整建议附带弹性 ±20% 方向检验小节"""
    result = pricing_skill("SKU001 双11活动价怎么定，把模型假设敏感性也列出来")
    text = result["data"]["analysis"]
    assert "【敏感性】" in text
    assert "×0.8" in text and "×1.2" in text
    assert ("保持成立" in text) or ("⚠️" in text)   # 稳健结论或翻转警示二选一


def test_sensitivity_deterministic_same_seed():
    """敏感性三档同种子: 两次调用输出完全一致 (确定性, 可复现)"""
    ctx = parse_context("当前售价 99，竞品均价 105")
    opt = optimize_pricing(ctx, seed=42)
    from app.skills.pricing_skill import _sensitivity_block
    assert _sensitivity_block(ctx, opt) == _sensitivity_block(ctx, opt)


def test_supplement_not_triggered_without_prior_advice():
    """首轮咨询(历史无建议): 正常完整模板, 不误入补充回答"""
    result = pricing_skill("SKU001 怎么定价", history=[])
    assert "损益优化沙盒定价建议" in result["data"]["analysis"]


def test_supplement_not_triggered_by_directive():
    """追问轮带明示调价指令: 走执行闭环, 不被去重逻辑拦截

    会话 SKU 记忆同时修正了执行目标: "那就降价 20%" 锚定正在讨论的
    SKU001 (库内真实价 99.0) → 79.2, 且审批单 product_id 就是 SKU001;
    旧逻辑会错误落到 default_hot_item 上 (答非所问商品)。
    """
    result = pricing_skill("那就降价 20% 吧", history=_HISTORY_WITH_ADVICE)
    assert result["is_executable"] is True
    assert result["execution_request"]["params"]["new_price"] == 79.2
    assert result["execution_request"]["params"]["product_id"] == "SKU001"


def test_disclaimer_suppressed_with_session_sku():
    """会话已锁定 SKU 的追问轮: 不再出现"未识别到具体商品"失忆话术"""
    result = pricing_skill("弹性假设会不会把结论带偏", history=_HISTORY_WITH_ADVICE)
    assert "未识别到具体商品" not in result["data"]["analysis"]


def test_disclaimer_kept_without_any_sku():
    """无任何 SKU 信息时(P8 诚实披露): 免责声明保留, 不因新逻辑丢失"""
    result = pricing_skill("帮我定个价", history=[])
    assert "未识别到具体商品" in result["data"]["analysis"]
