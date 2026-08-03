"""L4 蒙特卡洛沙盒求解器 (决策核心层)

流程: LLM 生成 5 个候选方案 -> 每个方案在沙盒中跑 1000 次蒙特卡洛模拟
      -> 选出期望净利润最高的方案返回给 answer 节点
可选增强:
- scipy.optimize.minimize 在最优解附近做局部精修
- optuna 全局自动搜索 (可选导入)
"""
import logging

import numpy as np

from app.config import OPTIMIZER_CONFIG
from .profit_model import ad_lift_factor

logger = logging.getLogger("optimizer.solver")

try:
    from scipy.optimize import minimize
    HAS_SCIPY = True
except ImportError:  # pragma: no cover
    HAS_SCIPY = False

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    HAS_OPTUNA = True
except ImportError:  # pragma: no cover
    HAS_OPTUNA = False


def _simulate_profits(price, ad_budget, inventory, competitor_price, n, rng, cfg,
                      base_sales=None, elastic=None, unit_cost=None):
    """向量化蒙特卡洛模拟, 返回长度为 n 的利润样本数组"""
    if base_sales is None:
        base_sales = cfg["base_sales"]
    if elastic is None:
        elastic = cfg["price_elasticity"]
    if unit_cost is None:
        unit_cost = cfg["unit_cost"]
    ad_budget = max(0.0, ad_budget or 0.0)
    lift = ad_lift_factor(ad_budget)

    # 竞品价扰动 -> 经弹性公式传导到需求
    comp = competitor_price * (1.0 + cfg["competitor_price_noise_std"] * rng.standard_normal(n))
    comp = np.maximum(comp, 0.01)
    # 需求扰动 (市场大盘波动)
    noise = 1.0 + cfg["demand_noise_std"] * rng.standard_normal(n)

    demand = base_sales * (1.0 + elastic * (comp - price) / comp) * lift * noise
    demand = np.clip(demand, 0.0, None)

    gmv = price * demand
    cogs = unit_cost * demand
    storage = inventory * cfg["storage_fee_rate"]
    rush = np.clip(demand - inventory, 0.0, None) * cfg["rush_fee_per_unit"]
    return gmv - cogs - ad_budget - storage - rush


def evaluate_candidate(candidate, context, n_sims=None, rng=None, cfg=None):
    """对单个候选方案做蒙特卡洛评估, 返回统计指标 (均值/标准差/95%置信区间)"""
    cfg = cfg or OPTIMIZER_CONFIG
    n_sims = n_sims or cfg["mc_simulations"]
    if rng is None:
        rng = np.random.default_rng()

    price = float(candidate["price"])
    ad_budget = float(candidate.get("ad_budget", context.get("ad_budget", cfg["default_ad_budget"])))
    inventory = float(candidate.get("inventory", context.get("inventory", cfg["default_inventory"])))
    competitor_price = float(context.get("competitor_price", cfg["default_competitor_price"]))

    profits = _simulate_profits(
        price, ad_budget, inventory, competitor_price, n_sims, rng, cfg,
        base_sales=context.get("base_sales"),
        elastic=context.get("elastic"),
        unit_cost=context.get("unit_cost"),
    )
    return {
        "candidate": {"price": round(price, 2), "ad_budget": round(ad_budget, 2), "inventory": inventory},
        "simulations": int(n_sims),
        "mean_profit": round(float(profits.mean()), 2),
        "std_profit": round(float(profits.std()), 2),
        "ci_lower": round(float(np.percentile(profits, 2.5)), 2),
        "ci_upper": round(float(np.percentile(profits, 97.5)), 2),
        "loss_probability": round(float((profits < 0).mean()), 4),
    }


def solve(candidates, context, n_sims=None, seed=None, cfg=None):
    """沙盒选优: 评估所有候选方案, 按期望净利润降序排序

    Args:
        candidates: [{"price": x, "ad_budget": y}, ...] (LLM 生成的 5 个候选)
        context: {"competitor_price", "inventory", "base_sales", "elastic", ...}
    Returns:
        {"best": {...}, "ranking": [...], "simulations": n}
    """
    cfg = cfg or OPTIMIZER_CONFIG
    if not candidates:
        raise ValueError("candidates is empty")
    rng = np.random.default_rng(seed)
    ranking = [evaluate_candidate(c, context, n_sims=n_sims, rng=rng, cfg=cfg) for c in candidates]
    ranking.sort(key=lambda r: r["mean_profit"], reverse=True)
    logger.info(
        "[solver] evaluated %d candidates x %d sims, best mean_profit=%.2f",
        len(ranking), n_sims or cfg["mc_simulations"], ranking[0]["mean_profit"],
    )
    return {"best": ranking[0], "ranking": ranking, "simulations": n_sims or cfg["mc_simulations"]}


def refine_with_scipy(candidate, context, cfg=None):
    """scipy.optimize.minimize 局部精修: 在候选方案附近搜索确定性利润更高的价格/预算组合

    Returns:
        dict | None: 精修后的方案与确定性利润; scipy 不可用或精修无收益时返回 None
    """
    if not HAS_SCIPY:
        logger.warning("[solver] scipy not available, skip refine")
        return None
    cfg = cfg or OPTIMIZER_CONFIG
    from .profit_model import estimate_profit

    price0 = float(candidate["price"])
    budget0 = float(candidate.get("ad_budget", context.get("ad_budget", cfg["default_ad_budget"])))
    inventory = float(context.get("inventory", cfg["default_inventory"]))
    competitor_price = float(context.get("competitor_price", cfg["default_competitor_price"]))
    kwargs = dict(
        inventory=inventory, competitor_price=competitor_price,
        base_sales=context.get("base_sales"), elastic=context.get("elastic"),
        unit_cost=context.get("unit_cost"), cfg=cfg,
    )

    def objective(x):
        return -estimate_profit(x[0], x[1], **kwargs)["profit"]

    bounds = [(competitor_price * 0.5, competitor_price * 1.5), (0.0, max(budget0 * 3, 3000.0))]
    try:
        res = minimize(objective, [price0, budget0], method="L-BFGS-B", bounds=bounds)
    except Exception as e:
        logger.warning("[solver] scipy minimize failed: %s", e)
        return None
    if not res.success:
        return None
    refined = estimate_profit(float(res.x[0]), float(res.x[1]), **kwargs)
    base = estimate_profit(price0, budget0, **kwargs)
    if refined["profit"] <= base["profit"]:
        return None
    return {
        "price": refined["price"],
        "ad_budget": refined["ad_budget"],
        "deterministic_profit": refined["profit"],
        "improvement": round(refined["profit"] - base["profit"], 2),
        "detail": refined,
    }


def solve_with_optuna(context, n_trials=100, seed=None, cfg=None):
    """optuna 全局搜索 (可选): 直接搜索确定性利润最优的价格/预算组合"""
    if not HAS_OPTUNA:
        logger.warning("[solver] optuna not available, skip")
        return None
    cfg = cfg or OPTIMIZER_CONFIG
    from .profit_model import estimate_profit

    competitor_price = float(context.get("competitor_price", cfg["default_competitor_price"]))
    inventory = float(context.get("inventory", cfg["default_inventory"]))

    def objective(trial):
        price = trial.suggest_float("price", competitor_price * 0.5, competitor_price * 1.5)
        budget = trial.suggest_float("ad_budget", 0.0, 5000.0)
        return estimate_profit(
            price, budget, inventory, competitor_price,
            base_sales=context.get("base_sales"), elastic=context.get("elastic"),
            unit_cost=context.get("unit_cost"), cfg=cfg,
        )["profit"]

    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    best = estimate_profit(
        study.best_params["price"], study.best_params["ad_budget"], inventory, competitor_price,
        base_sales=context.get("base_sales"), elastic=context.get("elastic"),
        unit_cost=context.get("unit_cost"), cfg=cfg,
    )
    return {
        "price": round(study.best_params["price"], 2),
        "ad_budget": round(study.best_params["ad_budget"], 2),
        "deterministic_profit": best["profit"],
        "detail": best,
    }
