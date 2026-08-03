"""L4 电商损益模型: 价格弹性需求预估 + 利润计算

核心公式 (参数调优入口: app/config.py OPTIMIZER_CONFIG):
    销量 = base_sales * (1 + elastic * (竞品价 - 自己的价) / 竞品价)
    GMV = 售价 * 销量
    预估利润 = GMV - 商品成本 - 广告成本 - 仓储成本 - 加急费
    (需求超出库存的部分通过加急补货满足, 每件加收 rush_fee)
"""
import math

from app.config import OPTIMIZER_CONFIG


def estimate_sales(price, competitor_price, base_sales=None, elastic=None):
    """价格弹性需求模型 (不含广告增益)"""
    if base_sales is None:
        base_sales = OPTIMIZER_CONFIG["base_sales"]
    if elastic is None:
        elastic = OPTIMIZER_CONFIG["price_elasticity"]
    if price < 0:
        return 0.0
    if competitor_price <= 0:
        return max(0.0, float(base_sales))
    sales = base_sales * (1.0 + elastic * (competitor_price - price) / competitor_price)
    return max(0.0, sales)


def ad_lift_factor(ad_budget, effectiveness=None):
    """广告投放对销量的提升系数: log 边际递减, budget=0 时为 1.0"""
    if effectiveness is None:
        effectiveness = OPTIMIZER_CONFIG["ad_effectiveness"]
    if ad_budget is None or ad_budget <= 0:
        return 1.0
    return 1.0 + effectiveness * math.log1p(ad_budget) / math.log1p(10000.0)


def estimate_profit(price, ad_budget, inventory, competitor_price,
                    base_sales=None, elastic=None, unit_cost=None, cfg=None):
    """确定性损益计算: 评估单个经营方案

    Args:
        price: 售价
        ad_budget: 广告预算
        inventory: 库存量
        competitor_price: 竞品均价
    Returns:
        dict: 含 demand/GMV/各项成本/profit 的明细
    """
    cfg = cfg or OPTIMIZER_CONFIG
    if unit_cost is None:
        unit_cost = cfg["unit_cost"]
    ad_budget = max(0.0, ad_budget or 0.0)

    demand = estimate_sales(price, competitor_price, base_sales, elastic) * ad_lift_factor(ad_budget)
    gmv = price * demand
    cogs = unit_cost * demand
    storage_cost = inventory * cfg["storage_fee_rate"]
    shortage = max(0.0, demand - inventory)
    rush_cost = shortage * cfg["rush_fee_per_unit"]
    profit = gmv - cogs - ad_budget - storage_cost - rush_cost

    return {
        "price": round(float(price), 2),
        "ad_budget": round(ad_budget, 2),
        "inventory": float(inventory),
        "competitor_price": float(competitor_price),
        "demand": round(demand, 2),
        "shortage": round(shortage, 2),
        "GMV": round(gmv, 2),
        "cogs": round(cogs, 2),
        "ad_cost": round(ad_budget, 2),
        "storage_cost": round(storage_cost, 2),
        "rush_cost": round(rush_cost, 2),
        "profit": round(profit, 2),
    }


def roi(profit_result):
    """ROI = 利润 / 总投入(广告+商品成本+仓储+加急)"""
    invested = (
        profit_result.get("ad_cost", 0)
        + profit_result.get("cogs", 0)
        + profit_result.get("storage_cost", 0)
        + profit_result.get("rush_cost", 0)
    )
    if invested <= 0:
        return 0.0
    return profit_result.get("profit", 0) / invested
