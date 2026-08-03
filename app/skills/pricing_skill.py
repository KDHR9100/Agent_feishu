# -*- coding: utf-8 -*-
"""L4 定价技能: 损益优化沙盒驱动的智能定价

流程:
1. 解析用户输入中的定价上下文 (当前售价/竞品均价/库存/广告预算), 缺失项用 OPTIMIZER_CONFIG 默认值兜底
2. 生成 5 个候选方案 (价格 x 广告预算组合; 生产环境由 LLM 生成, 此处为确定性模板保证可复现)
3. solver_engine 对每个候选跑 1000 次蒙特卡洛模拟, 选出期望净利润最高者
4. 输出 "建议降价 X%, ROI 提升 Y%" 并附 95% 模拟置信区间
5. 携带 is_executable=True 与 execution_request, 交由 executor 审批闭环执行 (绝不直接改价)
"""
import logging
import re

from app.config import OPTIMIZER_CONFIG
from app.optimizer.profit_model import estimate_profit, roi
from app.optimizer.solver_engine import solve

logger = logging.getLogger("skills.pricing")

# 候选方案模板: (价格倍率, 广告预算倍率) — 覆盖激进冲量到稳健保利区间
CANDIDATE_TEMPLATE = [
    (0.90, 1.20),   # C1 激进降价冲量
    (0.95, 1.10),   # C2 温和降价 + 小幅加投
    (1.00, 1.00),   # C3 维持现状基线
    (1.03, 0.85),   # C4 小幅提价保利润
    (1.08, 0.70),   # C5 提价 + 收缩广告
]

# 可执行动作标记: skill_executor 据此走 executor 审批闭环
IS_EXECUTABLE = True
ACTION_NAME = "update_price"


def _parse_number(text, keywords):
    """从用户输入中提取关键词后的数值, 如 '当前售价 99 元' / '竞品价:105'"""
    for kw in keywords:
        m = re.search(r"%s\s*[:：]?\s*(\d+(?:\.\d+)?)" % re.escape(kw), text)
        if m:
            return float(m.group(1))
    return None


def parse_context(user_input):
    """解析定价上下文, 缺失项回退到 OPTIMIZER_CONFIG 默认值"""
    cfg = OPTIMIZER_CONFIG
    user_input = user_input or ""
    return {
        "current_price": _parse_number(user_input, ["当前售价", "当前价格", "现价", "售价"])
        or cfg["default_price"],
        "competitor_price": _parse_number(user_input, ["竞品均价", "竞品价", "竞对价"])
        or cfg["default_competitor_price"],
        "inventory": _parse_number(user_input, ["库存量", "库存"]) or cfg["default_inventory"],
        "ad_budget": _parse_number(user_input, ["广告预算", "预算"]) or cfg["default_ad_budget"],
    }


def build_candidates(current_price, ad_budget):
    """围绕当前价格/预算生成 5 个候选方案"""
    return [
        {
            "id": "C%d" % (i + 1),
            "price": round(current_price * pf, 2),
            "ad_budget": round(ad_budget * af, 2),
        }
        for i, (pf, af) in enumerate(CANDIDATE_TEMPLATE)
    ]


def optimize_pricing(ctx, n_sims=None, seed=None):
    """沙盒核心: 返回 best 评估结果 + 与现状对比的全部指标"""
    cfg = OPTIMIZER_CONFIG
    context = {
        "competitor_price": ctx["competitor_price"],
        "inventory": ctx["inventory"],
        "base_sales": cfg["base_sales"],
        "elastic": cfg["price_elasticity"],
        "ad_budget": ctx["ad_budget"],
    }
    candidates = build_candidates(ctx["current_price"], ctx["ad_budget"])
    result = solve(candidates, context, n_sims=n_sims, seed=seed)
    best = result["best"]

    # 现状基线 (确定性口径, 用于 ROI 对比)
    current_plan = estimate_profit(
        ctx["current_price"], ctx["ad_budget"], ctx["inventory"], ctx["competitor_price"]
    )
    best_plan = estimate_profit(
        best["candidate"]["price"], best["candidate"]["ad_budget"],
        ctx["inventory"], ctx["competitor_price"],
    )
    current_roi = roi(current_plan)
    best_roi = roi(best_plan)

    change_pct = (best["candidate"]["price"] - ctx["current_price"]) / ctx["current_price"]
    roi_lift_pct = (
        (best_roi - current_roi) / abs(current_roi) * 100.0 if current_roi else 0.0
    )
    return {
        "context": ctx,
        "candidates": candidates,
        "best": best,
        "ranking": result["ranking"],
        "simulations": result["simulations"],
        "current_roi": round(current_roi, 4),
        "best_roi": round(best_roi, 4),
        "change_pct": round(change_pct * 100.0, 2),
        "roi_lift_pct": round(roi_lift_pct, 2),
        "current_plan": current_plan,
        "best_plan": best_plan,
    }


def _render_text(opt):
    """渲染飞书回复文本 (结论先行 + 分层论证)"""
    best = opt["best"]
    ctx = opt["context"]
    cand = best["candidate"]
    direction = "降价" if opt["change_pct"] < 0 else ("涨价" if opt["change_pct"] > 0 else "维持原价")
    roi_arrow = "提升" if opt["roi_lift_pct"] >= 0 else "下降"
    lines = [
        "📊 损益优化沙盒定价建议（%d 次蒙特卡洛模拟）" % opt["simulations"],
        "",
        "【结论】建议%s %.1f%%：%.2f 元 → %.2f 元，ROI %s %.1f%%"
        % (direction, abs(opt["change_pct"]), ctx["current_price"], cand["price"],
           roi_arrow, abs(opt["roi_lift_pct"])),
        "",
        "【上下文】竞品均价 %.2f 元 | 库存 %.0f 件 | 广告预算 %.0f 元 → 建议调整为 %.0f 元"
        % (ctx["competitor_price"], ctx["inventory"], ctx["ad_budget"], cand["ad_budget"]),
        "【预期收益】期望净利润 %.0f 元（95%% 模拟置信区间 [%.0f, %.0f]）"
        % (best["mean_profit"], best["ci_lower"], best["ci_upper"]),
        "【风险】模拟亏损概率 %.2f%%；利润波动 σ=%.0f 元"
        % (best["loss_probability"] * 100.0, best["std_profit"]),
        "【ROI】当前 %.2f → 优化后 %.2f" % (opt["current_roi"], opt["best_roi"]),
        "",
        "✅ 该方案已通过沙盒验证。如需执行调价，将进入人工审批流程（Agent 不会自动改价）。",
    ]
    return "\n".join(lines)


def pricing_skill(user_input, file_path=None, file_content=None, tool_result=None):
    """技能入口: 签名与其余 12 个技能保持一致"""
    ctx = parse_context(user_input)
    logger.info(
        "[pricing_skill] ctx=%s input_preview=%s",
        ctx, (user_input or "")[:60],
    )
    opt = optimize_pricing(ctx)
    text = _render_text(opt)
    cand = opt["best"]["candidate"]
    return {
        "type": "analysis",
        "data": {"analysis": text},
        "is_executable": IS_EXECUTABLE,
        "execution_request": {
            "action": ACTION_NAME,
            "params": {
                "product_id": "default_hot_item",
                "old_price": ctx["current_price"],
                "new_price": cand["price"],
                "new_ad_budget": cand["ad_budget"],
            },
            "description": "将爆款商品 %.2f 元调整为 %.2f 元（%s %.1f%%）"
            % (ctx["current_price"], cand["price"],
               "降价" if opt["change_pct"] < 0 else "涨价", abs(opt["change_pct"])),
        },
        "optimizer_result": {
            "simulations": opt["simulations"],
            "change_pct": opt["change_pct"],
            "roi_lift_pct": opt["roi_lift_pct"],
            "mean_profit": opt["best"]["mean_profit"],
            "ci_lower": opt["best"]["ci_lower"],
            "ci_upper": opt["best"]["ci_upper"],
            "loss_probability": opt["best"]["loss_probability"],
        },
    }
