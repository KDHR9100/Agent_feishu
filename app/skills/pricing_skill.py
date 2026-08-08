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


def _live_store_price(product_id="default_hot_item"):
    """读取店铺执行层的实时现价, 使定价建议建立在最新已执行价格之上

    用于用户未明示 "当前售价" 时的回退源 (优先级高于 OPTIMIZER_CONFIG 默认值);
    任何异常(适配器未就绪/真实平台预留实现抛错)都安全降级为 None, 不阻塞技能。
    """
    try:
        from app.executor.platform_adapter import get_store_api
        price = get_store_api().get_price(product_id)
        return float(price) if price else None
    except Exception:
        return None


# ── P4: 负价格显式拒绝 —— 负价不是价格, 不进入任何计算 ──
_NEGATIVE_PRICE_RE = re.compile(
    r"(?:定价|售价|价格|设为|设价|定价为|设价为|改为|改成|调至|调到|调整到|降到|降至|降低到|低到)"
    r"[^。！？!?\n]{0,6}?[−\-]\s*\d+(?:\.\d+)?"
)

# ── P3: 中文数字折扣换算 ("八八折"→8.8, "十折"→10.0) ──
_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
_CN_FOLD_RE = re.compile(r"[一二两三四五六七八九十]{1,2}")


def _cn_fold_to_float(s):
    """把中文折扣表达转成 float, 如 '八八'→8.8, '八'→8.0, '十'→10.0"""
    chars = [c for c in (s or "") if c in _CN_DIGITS]
    if not chars:
        return None
    if len(chars) == 1:
        return float(_CN_DIGITS[chars[0]])
    return float("%d.%d" % (_CN_DIGITS[chars[0]], _CN_DIGITS[chars[1]]))


# 折扣指令: "打 8 折" / "打8.5折" / "五折卖" / "3折出售" / "打八八折" / "88折清仓"
_FOLD_RE = re.compile(
    r"(?:打\s*([0-9]{1,2}(?:\.[0-9])?|[一二两三四五六七八九十]{1,2})\s*折"
    r"|([0-9]{1,2}(?:\.[0-9])?|[一二两三四五六七八九十]{1,2})\s*折\s*(?:卖|售|挂|出|执行)"
    # 裸 "NN折": 要求前后无其它数字, 且后不接 "优惠/折扣"(那是百分比语义), 避免误吞
    r"|(?<![\d.])([0-9]{1,2}(?:\.[0-9])?|[一二两三四五六七八九十]{1,2})\s*折(?![\d折优扣]))"
)


def _extract_product_id(user_input):
    """从用户输入中提取显式 SKU/商品编号; 未提及时返回 None"""
    m = re.search(r"(SKU[\s\-_]?[A-Za-z0-9\-_]+|商品\s*(?:ID|编号|id)?\s*[:：]?\s*[A-Za-z0-9\-]{3,})",
                  user_input or "", re.IGNORECASE)
    return m.group(1).strip() if m else None


# 用户明示目标价的口语关键词 (如 "降到 101" / "调高到 120" / "改为 89.9")
# 注意: "降价到/涨价到/提价到" 必须先于金额指令解析, 否则 "降价到99元" 会被误读为 "降99元"
TARGET_PRICE_KEYWORDS = [
    "降价到", "涨价到", "提价到",
    "再降到", "降到", "调低到", "降低到", "降至", "调低至", "低到",
    "再涨到", "涨到", "调高到", "提高到", "升至", "高到",
    "调整到", "调到", "调至", "改成", "改为", "设为",
]


def _parse_target_price(user_input):
    """提取用户明确指定的目标价; 未明示时返回 None (不干扰纯优化场景)

    R2: 含竞品/对手等市场描述的分句 (如 "竞品降到39元") 不是用户自己的
    目标价指令, 先剔除再解析, 避免把竞品价格误当成执行目标。
    """
    text = user_input or ""
    clauses = re.split(r"[。！？!?；;，,\n]", text)
    kept = [c for c in clauses if not any(w in c for w in _TARGET_GUARD_WORDS)]
    return _parse_number("，".join(kept), TARGET_PRICE_KEYWORDS)



# 明示调价指令: 方向词 + 幅度(百分比或金额); "竞品/对手降价" 等市场描述不算指令
_DIRECTIVE_GUARD_WORDS = ["竞品", "对手", "别家", "同行"]
# R2: 目标价解析同样需要剔除竞品语境分句
_TARGET_GUARD_WORDS = ["竞品", "对手", "别家", "同行", "友商"]
# R2: 咨询类问句标记 —— "要不要跟进降价?" 是征询建议, 不是执行指令
_CONSULTATIVE_MARKS = [
    "要不要", "该不该", "是否要", "是否应该", "需不需要", "跟不跟", "要不要跟进",
]


def is_consultative(user_input):
    """R2: 判断是否为征询建议的咨询问句 (要不要/该不该...)

    供 pricing_skill 与 workflow.skill_executor 共用: plan-execute 模式下
    步骤输入会被规划器改写, 技能内部可能看不到原始问句, 需在工作流层用
    原始 user_input 复查。
    """
    return any(m in (user_input or "") for m in _CONSULTATIVE_MARKS)
_UP_WORDS = r"(?:涨价|上涨|上调|提价|加价|调高|提高|涨)"
_DOWN_WORDS = r"(?:降价|下调|调低|降低|降)"
_PCT_UNIT = r"\s*[%％个点]"
_MONEY_UNIT = r"\s*(?:元|块钱|块|¥|￥)"


def _parse_directive(user_input, current_price):
    """解析用户明示的调价指令, 返回 {"price": 目标价, "note": 描述} 或 None

    支持: 涨价 10% / 降 5 个点 / 加 20 元 / 便宜 10 块 / 打 8 折 / 五折卖 等;
    含 "竞品/对手" 的市场描述不视为指令; 计算结果 <=0 视为无效。
    """
    text = user_input or ""
    if any(w in text for w in _DIRECTIVE_GUARD_WORDS):
        return None
    base = max(float(current_price or 0.0), 0.0)
    # 折扣指令 (先于百分比分支, 避免 "打折" 被误读): 打 8 折 / 打8.5折 / 五折卖
    m = _FOLD_RE.search(text)
    if m and base > 0:
        raw = m.group(1) or m.group(2) or m.group(3)
        fold = _cn_fold_to_float(raw) if _CN_FOLD_RE.fullmatch(raw or "") else None
        if fold is None:
            try:
                fold = float(raw)
            except (TypeError, ValueError):
                fold = None
        # 兼容 "88折" = 8.8 折 的口语写法
        if fold is not None and fold > 10.0:
            fold = fold / 10.0
        if fold is not None and 0 < fold <= 10.0:
            price = round(base * fold / 10.0, 2)
            note = "打 %g 折" % fold
            if fold < 3:
                note += "（深度折扣，请注意利润风险）"
            return {"price": price, "note": note}
    # 百分比指令: 涨 10% / 降价 5 个点
    m = re.search(_UP_WORDS + r"\D{0,4}?(\d+(?:\.\d+)?)" + _PCT_UNIT, text)
    if m:
        return {"price": round(base * (1 + float(m.group(1)) / 100.0), 2),
                "note": "涨价 %.1f%%" % float(m.group(1))}
    m = re.search(_DOWN_WORDS + r"\D{0,4}?(\d+(?:\.\d+)?)" + _PCT_UNIT, text)
    if m:
        return {"price": round(base * (1 - float(m.group(1)) / 100.0), 2),
                "note": "降价 %.1f%%" % float(m.group(1))}
    # 金额指令: 加 20 元 / 便宜 10 块
    m = re.search(r"(?:加价|提价|加|涨)" + r"\D{0,4}?(\d+(?:\.\d+)?)" + _MONEY_UNIT, text)
    if m:
        return {"price": round(base + float(m.group(1)), 2),
                "note": "上调 %.2f 元" % float(m.group(1))}
    m = re.search(r"(?:降|减|便宜)" + r"\D{0,4}?(\d+(?:\.\d+)?)" + _MONEY_UNIT, text)
    if m:
        return {"price": round(base - float(m.group(1)), 2),
                "note": "下调 %.2f 元" % float(m.group(1))}
    return None


def parse_context(user_input):
    """解析定价上下文, 缺失项回退到 OPTIMIZER_CONFIG 默认值"""
    cfg = OPTIMIZER_CONFIG
    user_input = user_input or ""
    return {
        # 回退优先级: 用户口语明示 > 店铺实时价 > 配置默认值
        "current_price": _parse_number(user_input, ["当前售价", "当前价格", "现价", "售价"])
        or _live_store_price()
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


def _render_text(opt, target_price=None, target_plan=None):
    """渲染飞书回复文本 (结论先行 + 分层论证)"""
    best = opt["best"]
    ctx = opt["context"]
    cand = best["candidate"]
    direction = "降价" if opt["change_pct"] < 0 else ("涨价" if opt["change_pct"] > 0 else "维持原价")
    roi_arrow = "提升" if opt["roi_lift_pct"] >= 0 else "下降"
    # 【结论】行: 用户明示目标价时以指示为准, 沙盒最优价降级为顾问意见
    if target_price is not None and target_plan is not None:
        t_chg = (target_price - ctx["current_price"]) / ctx["current_price"] * 100.0
        t_dir = "降价" if t_chg < 0 else ("涨价" if t_chg > 0 else "维持原价")
        conclusion = (
            "【结论】按您的指示%s：%.2f 元 → %.2f 元（%s %.1f%%）\n"
            "【沙盒意见】蒙特卡洛最优价 %.2f 元（期望利润 %.0f 元）；"
            "您指定价格的期望利润 %.0f 元。以您的指示为准，进入审批流程"
            % (t_dir, ctx["current_price"], target_price, t_dir, abs(t_chg),
               cand["price"], best["mean_profit"], target_plan.get("profit", 0.0))
        )
    else:
        conclusion = (
            "【结论】建议%s %.1f%%：%.2f 元 → %.2f 元，ROI %s %.1f%%"
            % (direction, abs(opt["change_pct"]), ctx["current_price"], cand["price"],
               roi_arrow, abs(opt["roi_lift_pct"]))
        )
    lines = [
        "📊 损益优化沙盒定价建议（%d 次蒙特卡洛模拟）" % opt["simulations"],
        "",
        conclusion,
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
    user_input = user_input or ""
    # P4: 负价格显式拒绝 —— 不进入任何计算, 也不生成审批单
    if _NEGATIVE_PRICE_RE.search(user_input):
        return {
            "type": "analysis",
            "data": {"analysis":
                     "【无法执行】价格为负数不是合法的定价操作，已拒绝该请求。\n"
                     "如果您想表达的是降价幅度（如“降 50 元”“降价 10%”），请直接说明降幅；"
                     "或给出一个大于 0 的目标价格，我再为您测算并走审批流程。"},
            "is_executable": False,
            "execution_request": None,
        }
    ctx = parse_context(user_input)
    logger.info(
        "[pricing_skill] ctx=%s input_preview=%s",
        ctx, user_input[:60],
    )
    opt = optimize_pricing(ctx)
    cand = opt["best"]["candidate"]
    # 意图分层: 用户明示指令(目标价/涨跌幅)直接执行, 优化器仅作顾问;
    # 无明示指令(利润目标/ROI 诉求/怎么定价)才用蒙特卡洛最优价
    consultative = is_consultative(user_input)
    target_price = None if consultative else _parse_target_price(user_input)
    directive = None if (consultative or target_price) else _parse_directive(
        user_input, ctx["current_price"])
    if target_price is not None and target_price > 0:
        exec_price = round(target_price, 2)
        target_plan = estimate_profit(
            exec_price, cand["ad_budget"], ctx["inventory"], ctx["competitor_price"])
    elif directive and directive["price"] > 0:
        exec_price = directive["price"]
        target_plan = estimate_profit(
            exec_price, cand["ad_budget"], ctx["inventory"], ctx["competitor_price"])
    else:
        exec_price = cand["price"]
        target_plan = None
    text = _render_text(
        opt,
        target_price=exec_price if target_plan else None,
        target_plan=target_plan,
    )
    # P8: 无具体商品且未明示现价时, 显式披露默认口径, 避免"编造上下文"观感
    has_sku = bool(_extract_product_id(user_input))
    user_price = _parse_number(user_input, ["当前售价", "当前价格", "现价", "售价"])
    if not has_sku and user_price is None:
        text = ("⚠️ 未识别到具体商品/SKU，以下按店铺默认基准商品测算"
                "（当前基准价 %.2f 元来自系统默认值，非真实在售价格）。\n%s"
                % (ctx["current_price"], text))
        text += ("\n【口径说明】竞品均价 %.2f 元、库存 %.0f 件、广告预算 %.0f 元均为系统默认基准值，"
                 "如需精确测算请提供 SKU 编号与实际现价/库存/预算。"
                 % (ctx["competitor_price"], ctx["inventory"], ctx["ad_budget"]))
    # R2: 咨询类问题 ("我要不要跟进降价?") 仅输出沙盒分析,
    # is_executable=False → skill_executor 不会走 executor 审批闭环, 不产生审批卡片
    if consultative:
        text = ("【咨询模式】您是在征询决策建议，以下为沙盒测算分析，未发起任何调价操作。\n\n"
                + text)
        return {
            "type": "analysis",
            "data": {"analysis": text},
            "is_executable": False,
            "execution_request": None,
        }
    exec_change_pct = (exec_price - ctx["current_price"]) / ctx["current_price"] * 100.0
    product_id = _extract_product_id(user_input) or "default_hot_item"
    return {
        "type": "analysis",
        "data": {"analysis": text},
        "is_executable": IS_EXECUTABLE,
        "execution_request": {
            "action": ACTION_NAME,
            "params": {
                "product_id": product_id,
                "old_price": ctx["current_price"],
                "new_price": exec_price,
                "new_ad_budget": cand["ad_budget"],
            },
            "description": "将商品 %s 由 %.2f 元调整为 %.2f 元（%s %.1f%%）"
            % (product_id, ctx["current_price"], exec_price,
               "降价" if exec_change_pct < 0 else "涨价", abs(exec_change_pct)),
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
