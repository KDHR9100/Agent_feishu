"""任务10 优化器测试: 验证损益模型公式与蒙特卡洛选优能力"""
import pytest

from app.config import OPTIMIZER_CONFIG
from app.optimizer.profit_model import estimate_sales, estimate_profit, ad_lift_factor, roi
from app.optimizer.solver_engine import (
    solve, evaluate_candidate, refine_with_scipy, solve_with_optuna,
    HAS_SCIPY, HAS_OPTUNA,
)


# ---------- 价格弹性模型 ----------

def test_elasticity_formula_exact():
    # 销量 = 200 * (1 + 1.5 * (100 - 90) / 100) = 230
    sales = estimate_sales(90, 100, base_sales=200, elastic=1.5)
    assert abs(sales - 230.0) < 1e-9


def test_lower_price_higher_sales():
    assert estimate_sales(80, 100, 200, 1.5) > estimate_sales(100, 100, 200, 1.5)


def test_price_above_competitor_reduces_sales():
    assert estimate_sales(120, 100, 200, 1.5) < 200


def test_sales_never_negative():
    assert estimate_sales(10000, 100, 200, 1.5) == 0.0


def test_ad_lift_monotonic_and_diminishing():
    l0 = ad_lift_factor(0)
    l1 = ad_lift_factor(1000)
    l2 = ad_lift_factor(2000)
    assert l0 == 1.0
    assert l2 > l1 > l0
    # 边际递减: 第二个 1000 元带来的增益更小
    assert (l2 - l1) < (l1 - l0)


# ---------- 损益函数 ----------

def test_profit_structure_balance():
    r = estimate_profit(99, 800, 300, 105, base_sales=200, elastic=1.5, unit_cost=40)
    expected = r["GMV"] - r["cogs"] - r["ad_cost"] - r["storage_cost"] - r["rush_cost"]
    assert abs(r["profit"] - expected) < 0.05


def test_shortage_triggers_rush_cost():
    # 极低价格 -> 需求远超库存 -> 产生加急费
    r = estimate_profit(50, 0, 10, 105, base_sales=200, elastic=1.5, unit_cost=40)
    assert r["shortage"] > 0
    assert r["rush_cost"] > 0


def test_roi_definition():
    r = estimate_profit(99, 800, 300, 105)
    invested = r["ad_cost"] + r["cogs"] + r["storage_cost"] + r["rush_cost"]
    assert abs(roi(r) - r["profit"] / invested) < 1e-9


# ---------- 蒙特卡洛求解器 ----------

CONTEXT = {"competitor_price": 105.0, "inventory": 300.0, "base_sales": 200.0, "elastic": 1.5}


def test_evaluate_candidate_confidence_interval():
    r = evaluate_candidate({"price": 99, "ad_budget": 800}, CONTEXT, n_sims=1000)
    assert r["simulations"] == 1000
    assert r["ci_lower"] <= r["mean_profit"] <= r["ci_upper"]
    assert 0 <= r["loss_probability"] <= 1


def test_solver_picks_highest_mean():
    candidates = [
        {"price": 99, "ad_budget": 800},    # 合理方案
        {"price": 30, "ad_budget": 800},    # 低于成本价, 必亏
        {"price": 200, "ad_budget": 0},     # 远高于竞品, 销量崩
    ]
    result = solve(candidates, CONTEXT, n_sims=500, seed=42)
    means = [r["mean_profit"] for r in result["ranking"]]
    assert means == sorted(means, reverse=True)
    assert result["best"]["candidate"]["price"] == 99


def test_solver_beats_average_guess():
    """验证优化器选出的方案优于候选平均水准 (比瞎蒙强)"""
    candidates = [
        {"price": p, "ad_budget": b}
        for p, b in [(60, 2000), (85, 1200), (99, 800), (115, 400), (140, 100)]
    ]
    result = solve(candidates, CONTEXT, n_sims=500, seed=7)
    avg_mean = sum(r["mean_profit"] for r in result["ranking"]) / len(result["ranking"])
    assert result["best"]["mean_profit"] > avg_mean


def test_solver_reproducible_with_seed():
    c = [{"price": 99, "ad_budget": 800}]
    r1 = solve(c, CONTEXT, n_sims=300, seed=123)
    r2 = solve(c, CONTEXT, n_sims=300, seed=123)
    assert r1["best"]["mean_profit"] == r2["best"]["mean_profit"]


def test_solver_empty_candidates_raises():
    with pytest.raises(ValueError):
        solve([], CONTEXT)


# ---------- scipy 精修 / optuna ----------

@pytest.mark.skipif(not HAS_SCIPY, reason="scipy not installed")
def test_scipy_refine_not_worse():
    candidate = {"price": 110.0, "ad_budget": 1500.0}
    refined = refine_with_scipy(candidate, CONTEXT)
    # 精修要么有正收益, 要么返回 None(无收益), 不会变差
    if refined is not None:
        assert refined["improvement"] > 0


@pytest.mark.skipif(not HAS_OPTUNA, reason="optuna not installed")
def test_optuna_global_search():
    result = solve_with_optuna(CONTEXT, n_trials=30, seed=1)
    assert result is not None
    assert result["deterministic_profit"] > 0
