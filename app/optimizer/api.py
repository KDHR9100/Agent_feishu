# -*- coding: utf-8 -*-
"""L4 优化器 HTTP 接口层 (旁路挂载, main.py startup 时 include_router)"""
import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import OPTIMIZER_CONFIG
from app.optimizer.solver_engine import HAS_SCIPY, refine_with_scipy
from app.skills.pricing_skill import optimize_pricing

logger = logging.getLogger("optimizer.api")

router = APIRouter(prefix="/optimize", tags=["L4-optimizer"])


class PricingRequest(BaseModel):
    current_price: Optional[float] = None
    competitor_price: Optional[float] = None
    inventory: Optional[float] = None
    ad_budget: Optional[float] = None
    n_sims: Optional[int] = None
    seed: Optional[int] = None
    refine: bool = True


@router.post("/pricing")
def optimize_pricing_endpoint(req: PricingRequest):
    """Checkpoint 2 验收接口: 返回带模拟置信区间的最优定价 JSON"""
    cfg = OPTIMIZER_CONFIG
    ctx = {
        "current_price": req.current_price or cfg["default_price"],
        "competitor_price": req.competitor_price or cfg["default_competitor_price"],
        "inventory": req.inventory or cfg["default_inventory"],
        "ad_budget": req.ad_budget or cfg["default_ad_budget"],
    }
    opt = optimize_pricing(ctx, n_sims=req.n_sims, seed=req.seed)
    best = opt["best"]
    cand = best["candidate"]

    # 可选: scipy 局部精修, 若找到确定性利润更高的组合则附带返回
    refined = None
    if req.refine and HAS_SCIPY:
        refined = refine_with_scipy(
            {"price": cand["price"], "ad_budget": cand["ad_budget"]},
            {"competitor_price": ctx["competitor_price"], "inventory": ctx["inventory"]},
        )

    return {
        "status": "ok",
        "context": ctx,
        "recommended_price": cand["price"],
        "recommended_ad_budget": cand["ad_budget"],
        "change_pct": opt["change_pct"],
        "expected_profit": best["mean_profit"],
        "confidence_interval": {
            "level": "95%",
            "lower": best["ci_lower"],
            "upper": best["ci_upper"],
        },
        "std_profit": best["std_profit"],
        "loss_probability": best["loss_probability"],
        "roi_current": opt["current_roi"],
        "roi_recommended": opt["best_roi"],
        "roi_lift_pct": opt["roi_lift_pct"],
        "simulations": opt["simulations"],
        "scipy_refined": refined,
        "ranking": [
            {
                "price": r["candidate"]["price"],
                "ad_budget": r["candidate"]["ad_budget"],
                "mean_profit": r["mean_profit"],
                "ci": [r["ci_lower"], r["ci_upper"]],
            }
            for r in opt["ranking"]
        ],
    }
