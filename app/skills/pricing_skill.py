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


def _load_real_product_context(product_id):
    """按 SKU 从业务数据库查询真实经营上下文 (最近一期的库存/成交均价)

    P8 根治: 指定了 SKU 时必须用库内真实数据, 不得拿配置默认值冒充。
    只返回库中确有数据的字段; SKU 不存在/读取异常时返回 {}, 由调用方
    回退默认值并在展示层标注"示例基准"。
    """
    if not product_id:
        return {}
    try:
        from app.tools.database_tool import db_tool
        pid = str(product_id).strip()
        # _extract_product_id 的匹配结果可能带 "SKU" 前缀 (如 "SKU HY00000637"),
        # 归一化后再与库内 sku 比对
        pid_bare = re.sub(r"^SKU[\s\-_]*", "", pid, flags=re.IGNORECASE)
        rows = [
            r for r in db_tool.read_data("product_sales.csv")
            if str(r.get("sku", "")).strip().upper() in (pid.upper(), pid_bare.upper())
        ]
        if not rows:
            return {}
        latest = max(rows, key=lambda r: str(r.get("date", "")))

        def _num(row, key):
            try:
                return float(row.get(key))
            except (TypeError, ValueError):
                return None

        out = {}
        inv = _num(latest, "inventory")
        if inv is not None:
            out["inventory"] = inv
        avg_price = _num(latest, "avg_price")
        if avg_price and avg_price > 0:
            out["avg_price"] = avg_price
        return out
    except Exception as e:
        logger.warning("[pricing_skill] SKU=%s 真实数据查询失败: %s", product_id, e)
        return {}


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
    "调整到", "调价到", "调价为", "调到", "调至",
    "改价到", "改价为", "改成", "改为", "设为",
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
# R2: 征询式咨询标记 —— "要不要跟进降价?" 是征询建议, 不是执行指令
_CONSULTATIVE_MARKS = [
    "要不要", "该不该", "是否要", "是否应该", "需不需要", "跟不跟", "要不要跟进",
]
# 问价式咨询标记 —— "卖多少钱合适/定价建议" 只要建议, 没有给出任何要执行的
# 改价动作; 与"降价20%"这类调价指令危险程度完全不同, 只输出沙盒建议,
# 绝不产生执行请求/审批单
_ADVICE_QUESTION_MARKS = [
    "卖多少钱", "多少钱合适", "定多少钱", "定多少合适", "该定多少",
    "定价建议", "价格建议", "建议价", "怎么定价", "如何定价", "怎么定",
    "什么价合适", "什么价格合适", "帮我定价", "帮我定个价", "定个价",
    "建议卖", "定价多少",
]
# 批量调价措辞: 执行层只支持单商品改价, 整店/批量指令不能冒充单商品执行
_BATCH_MARKS = ["全店", "所有商品", "全部商品", "所有产品", "全部产品", "批量"]


def is_consultative(user_input):
    """判断是否为咨询问句 (征询建议 或 问价要建议), 供技能层与工作流层共用

    两类都属于"不动手只问意见":
    - 征询式: 要不要/该不该/是否要...
    - 问价式: 卖多少钱合适/定价建议/怎么定价...
    plan-execute 模式下步骤输入会被规划器改写, 技能内部可能看不到原始问句,
    需在工作流层用原始 user_input 复查。
    """
    s = user_input or ""
    return any(m in s for m in _CONSULTATIVE_MARKS) or \
        any(m in s for m in _ADVICE_QUESTION_MARKS)


def has_explicit_directive(user_input):
    """判断用户输入是否包含"明示调价指令"(目标价/涨跌幅/折扣)

    供技能入口与 workflow 层复查共用: 只有真指令才允许产生执行请求、
    进入审批闭环; 咨询问价("卖多少钱合适")一律返回 False。
    """
    user_input = user_input or ""
    if is_consultative(user_input):
        return False
    if _parse_target_price(user_input) is not None:
        return True
    ctx = parse_context(user_input)
    return bool(_parse_directive(user_input, ctx["current_price"]))
_UP_WORDS = r"(?:涨价|上涨|上调|提价|加价|调高|提高|涨)"
_DOWN_WORDS = r"(?:降价|下调|调低|降低|降)"
_PCT_UNIT = r"\s*[%％个点]"
_MONEY_UNIT = r"\s*(?:元|块钱|块|¥|￥)"


def _parse_directive(user_input, current_price):
    """解析用户明示的调价指令, 返回 {"price": 目标价, "note": 描述} 或 None

    支持: 涨价 10% / 降 5 个点 / 加 20 元 / 便宜 10 块 / 打 8 折 / 五折卖 等;
    含 "竞品/对手" 的分句视为市场描述予以剔除(但不影响其余分句中的真实指令);
    计算结果 <=0 视为无效。
    """
    text = user_input or ""
    # 按分句剔除竞品描述分句, 避免"竞品降价了4%"被误读为指令,
    # 同时不否决与之并存的真实指令(如"涨价10%(竞品均价105)")
    clauses = re.split(r"[，。！？；,!?;、]+", text)
    text = "，".join(
        c for c in clauses
        if c and not any(w in c for w in _DIRECTIVE_GUARD_WORDS)
    )
    if not text:
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
    # 百分比指令: 涨 10% / 降价 5 个点 (关键词与数字间允许少量词语, 如"调高爆款价格 10%")
    m = re.search(_UP_WORDS + r"\D{0,8}?(\d+(?:\.\d+)?)" + _PCT_UNIT, text)
    if m:
        return {"price": round(base * (1 + float(m.group(1)) / 100.0), 2),
                "note": "涨价 %.1f%%" % float(m.group(1))}
    m = re.search(_DOWN_WORDS + r"\D{0,8}?(\d+(?:\.\d+)?)" + _PCT_UNIT, text)
    if m:
        return {"price": round(base * (1 - float(m.group(1)) / 100.0), 2),
                "note": "降价 %.1f%%" % float(m.group(1))}
    # 金额指令: 加 20 元 / 便宜 10 块
    m = re.search(r"(?:加价|提价|加|涨)" + r"\D{0,8}?(\d+(?:\.\d+)?)" + _MONEY_UNIT, text)
    if m:
        return {"price": round(base + float(m.group(1)), 2),
                "note": "上调 %.2f 元" % float(m.group(1))}
    m = re.search(r"(?:降|减|便宜)" + r"\D{0,8}?(\d+(?:\.\d+)?)" + _MONEY_UNIT, text)
    if m:
        return {"price": round(base - float(m.group(1)), 2),
                "note": "下调 %.2f 元" % float(m.group(1))}
    return None


def parse_context(user_input):
    """解析定价上下文, 缺失项按优先级回退并记录来源

    回退优先级:
    - 当前售价: 用户口语明示 > 库内真实成交均价(指定 SKU 时) > 店铺实时价 > 配置默认值
    - 库存:     用户口语明示 > 库内真实库存(指定 SKU 时) > 配置默认值
    - 竞品均价/广告预算: 用户口语明示 > 配置默认值 (库内无竞品/预算数据)

    _sources 记录各字段来源, 供 _render_text 如实标注"真实数据/示例基准",
    杜绝把默认值当真实上下文展示 (P8)。
    """
    cfg = OPTIMIZER_CONFIG
    user_input = user_input or ""
    product_id = _extract_product_id(user_input)
    real = _load_real_product_context(product_id) if product_id else {}
    sources = {}

    user_price = _parse_number(user_input, ["当前售价", "当前价格", "现价", "售价"])
    if user_price is not None:
        current_price, sources["current_price"] = user_price, "用户明示"
    elif "avg_price" in real:
        current_price = real["avg_price"]
        sources["current_price"] = "库内真实数据"
    elif _live_store_price():
        current_price, sources["current_price"] = _live_store_price(), "店铺实时价"
    else:
        current_price, sources["current_price"] = cfg["default_price"], "示例基准"

    user_comp = _parse_number(user_input, ["竞品均价", "竞品价", "竞对价"])
    if user_comp is not None:
        competitor_price, sources["competitor_price"] = user_comp, "用户明示"
    else:
        competitor_price = cfg["default_competitor_price"]
        sources["competitor_price"] = "示例基准"

    user_inv = _parse_number(user_input, ["库存量", "库存"])
    if user_inv is not None:
        inventory, sources["inventory"] = user_inv, "用户明示"
    elif "inventory" in real:
        inventory, sources["inventory"] = real["inventory"], "库内真实数据"
    else:
        inventory, sources["inventory"] = cfg["default_inventory"], "示例基准"

    user_budget = _parse_number(user_input, ["广告预算", "预算"])
    if user_budget is not None:
        ad_budget, sources["ad_budget"] = user_budget, "用户明示"
    else:
        ad_budget, sources["ad_budget"] = cfg["default_ad_budget"], "示例基准"

    return {
        "current_price": current_price,
        "competitor_price": competitor_price,
        "inventory": inventory,
        "ad_budget": ad_budget,
        "_sources": sources,
        "_sku_in_db": bool(real),
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
    # P8 根治: 上下文逐项标注数据来源 —— 库内真实数据照实展示,
    # 配置默认值必须标注"示例基准", 绝不把假数据伪装成真实经营上下文
    src = ctx.get("_sources", {})
    _src_tag = {
        "库内真实数据": "库内真实数据",
        "店铺实时价": "店铺实时价",
        "示例基准": "示例基准，非真实数据",
    }

    def _ctx_item(name, val, key):
        tag = _src_tag.get(src.get(key, ""))
        return "%s %s%s" % (name, val, ("（%s）" % tag) if tag else "")

    ctx_line = "【上下文】%s | %s | %s | %s → 建议广告预算调整为 %.0f 元" % (
        _ctx_item("当前售价", "%.2f 元" % ctx["current_price"], "current_price"),
        _ctx_item("库存", "%.0f 件" % ctx["inventory"], "inventory"),
        _ctx_item("竞品均价", "%.2f 元" % ctx["competitor_price"], "competitor_price"),
        _ctx_item("广告预算", "%.0f 元" % ctx["ad_budget"], "ad_budget"),
        cand["ad_budget"],
    )
    lines = [
        "📊 损益优化沙盒定价建议（%d 次蒙特卡洛模拟）" % opt["simulations"],
        "",
        conclusion,
        "",
        ctx_line,
    ]
    if ctx.get("_sku_in_db") and ctx["inventory"] <= 0:
        lines.append(
            "⚠️ 注意：该 SKU 库内库存为 0 件，以上模拟利润已计入加急补货成本，"
            "执行调价前请先确认补货计划。"
        )
    lines += [
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
    # 批量调价措辞 ("全店打8折"): 执行层只支持单商品改价,
    # 批量指令不能冒充单商品执行 —— 如实说明限制, 不产生执行请求
    if any(m in user_input for m in _BATCH_MARKS):
        return {
            "type": "analysis",
            "data": {"analysis":
                     "【暂不支持批量调价】全店/多商品批量调价目前无法执行，"
                     "本次未发起任何调价操作。请按单个 SKU 下达调价指令"
                     "（如“把 SKU HY00000637 降价 20%”），逐一走审批执行。"},
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
    # 严格区分"问价咨询"与"调价执行"(两者危险程度完全不同):
    # 只有明示调价指令(目标价/涨跌幅/折扣)才产生执行请求、进入审批闭环;
    # 咨询问句("卖多少钱合适")与其余无明示指令的输入只输出沙盒建议,
    # is_executable=False → 不走 executor 审批闭环, 不产生审批卡片
    explicit_directive = (
        (target_price is not None and target_price > 0)
        or bool(directive and directive["price"] > 0)
    )
    if not explicit_directive:
        if consultative:
            text = ("【咨询模式】您是在征询决策建议，以下为沙盒测算分析，未发起任何调价操作。\n\n"
                    + text)
        else:
            text = ("【建议模式】您未下达明确的调价指令，以下仅为定价建议，未发起任何调价操作。"
                    "如需执行，请直接下达明确指令（如“降价 20%”“调价到 79.2 元”），"
                    "经您审批确认后才会生效。\n\n"
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
