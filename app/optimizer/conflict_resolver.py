# -*- coding: utf-8 -*-
"""L4 多目标冲突仲裁器 (任务12): 帕累托最优解 + 飞书决策看板

商业原则: 把最终道德/利益权衡交给人类, Agent 负责把选项算清楚。

流程:
1. detect_conflicts: 识别用户请求中相互冲突的指标 (省预算+保销量+清库存 等),
   超过 2 个冲突目标时启动仲裁
2. 网格枚举价格×预算组合, 用损益模型计算每个目标维度的标准化分数 (0-100)
3. 非支配排序生成帕累托前沿面 (scipy 无 pareto_front, 此处自实现)
4. 从前沿面取两个代表方案: A 激进获客 / B 稳健保利, 附飞书决策看板卡片
5. 用户点选后才调用执行器 (apply_choice -> verify_and_execute)
"""
import logging
import re
import threading
import uuid

from app.config import OPTIMIZER_CONFIG
from app.optimizer.profit_model import estimate_profit

logger = logging.getLogger("optimizer.conflict")

# 冲突目标关键词表: 目标名 -> 触发关键词
GOAL_KEYWORDS = {
    "profit": ["保利润", "利润", "盈利", "毛利", "赚钱"],
    "sales": ["保销量", "冲量", "销量", "GMV", "出单"],
    "budget": ["省预算", "预算", "省钱", "控成本", "少花钱"],
    "inventory": ["清库存", "清仓", "去库存", "库存压力"],
}

GOAL_LABELS = {
    "profit": "利润",
    "sales": "销量",
    "budget": "省预算",
    "inventory": "清库存",
}

# 触发仲裁的最小冲突目标数 (指令: 超过 2 个相互冲突的指标)
CONFLICT_MIN_GOALS = 3

# P5: 恰好 2 个目标时的显式冲突句式 —— 用户明确要求两者兼得/同时极值, 本质上不可同时满足
# 仅认强并列句式 (既要X又要Y / 都要 / 兼顾), 避免 "...的同时" 等描述性语句误触发
_CONFLICT_CONNECTIVE_RE = re.compile(
    r"[既又][是要想]?.{0,16}[又也还][是要想]?"
    r"|都[要得想]"
    r"|兼顾"
)
# 极值词: 要求目标达到极端 (利润/销量 最大化 等)
_CONFLICT_MAXIMIZER_RE = re.compile(r"最大化|拉满|都做到最好")


def _explicit_two_goal_conflict(user_input):
    """2 个目标 + 显式并列/极值句式 → 判定为冲突 (P5)"""
    text = user_input or ""
    return bool(_CONFLICT_CONNECTIVE_RE.search(text)
                or _CONFLICT_MAXIMIZER_RE.search(text))


def detect_conflicts(user_input):
    """从用户输入中识别冲突目标, 返回匹配到的目标名列表"""
    user_input = user_input or ""
    goals = []
    for goal, keywords in GOAL_KEYWORDS.items():
        if any(kw in user_input for kw in keywords):
            goals.append(goal)
    return goals


def is_conflicted(goals, user_input=""):
    """冲突判定: >=3 个目标必然冲突;
    恰好 2 个目标时, 仅当原文含显式并列/极值句式才判为冲突 (P5)。
    user_input 为可选参数, 旧调用签名完全兼容。"""
    if len(goals) >= CONFLICT_MIN_GOALS:
        return True
    if len(goals) == 2 and user_input:
        return _explicit_two_goal_conflict(user_input)
    return False


def normalize_scores(values):
    """将一组原始值线性归一化到 0-100 分 (最大值=100, 最小值=0; 全等时均为 100)"""
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [100.0] * len(values)
    return [round((v - lo) / (hi - lo) * 100.0, 1) for v in values]


def pareto_front(points, maximize=True):
    """非支配排序 (网格枚举替代 scipy.pareto_front): 返回帕累托前沿点索引

    points: list[tuple[float, ...]] 每个点为一个目标维度向量
    """
    sign = 1.0 if maximize else -1.0
    front = []
    n = len(points)
    for i in range(n):
        dominated = False
        for j in range(n):
            if i == j:
                continue
            pi = [sign * x for x in points[i]]
            pj = [sign * x for x in points[j]]
            # j 支配 i: j 在所有维度不差于 i, 且至少一个维度严格更优
            if all(pj[k] >= pi[k] for k in range(len(pi))) and \
               any(pj[k] > pi[k] for k in range(len(pi))):
                dominated = True
                break
        if not dominated:
            front.append(i)
    return front


def enumerate_grid(ctx, price_steps=7, budget_steps=7):
    """网格枚举价格×预算组合, 返回每个组合的损益明细"""
    cfg = OPTIMIZER_CONFIG
    comp = ctx.get("competitor_price", cfg["default_competitor_price"])
    inventory = ctx.get("inventory", cfg["default_inventory"])
    current_price = ctx.get("current_price", cfg["default_price"])
    current_budget = ctx.get("ad_budget", cfg["default_ad_budget"])

    price_lo, price_hi = comp * 0.7, comp * 1.1
    budget_lo, budget_hi = 0.0, max(current_budget * 1.5, 1000.0)
    plans = []
    for i in range(price_steps):
        price = price_lo + (price_hi - price_lo) * i / (price_steps - 1)
        for j in range(budget_steps):
            budget = budget_lo + (budget_hi - budget_lo) * j / (budget_steps - 1)
            detail = estimate_profit(
                round(price, 2), round(budget, 2), inventory, comp,
                base_sales=ctx.get("base_sales"), elastic=ctx.get("elastic"),
            )
            plans.append(detail)
    return plans


def score_goals(goals, plans, ctx):
    """为每个网格方案在检测到的目标维度上打 0-100 标准化分数

    - profit: 预估利润越高越好
    - sales: 预估销量越高越好
    - budget: 广告预算越低越好 (省预算)
    - inventory: 销量/库存 比值越高越好 (清库存力度, 封顶 1.0)
    """
    cfg = OPTIMIZER_CONFIG
    inventory = ctx.get("inventory", cfg["default_inventory"]) or 1.0
    raw = {goal: [] for goal in goals}
    for p in plans:
        for goal in goals:
            if goal == "profit":
                raw[goal].append(p["profit"])
            elif goal == "sales":
                raw[goal].append(p["demand"])
            elif goal == "budget":
                raw[goal].append(-p["ad_budget"])  # 越省分越高
            elif goal == "inventory":
                raw[goal].append(min(p["demand"] / inventory, 1.0))
    return {goal: normalize_scores(raw[goal]) for goal in goals}


def _build_execution_request(plan, ctx):
    return {
        "action": "update_price",
        "params": {
            "product_id": "default_hot_item",
            "old_price": ctx.get("current_price", OPTIMIZER_CONFIG["default_price"]),
            "new_price": plan["price"],
            "new_ad_budget": plan["ad_budget"],
        },
        "description": "仲裁方案: 调价至 %.2f 元, 广告预算 %.0f 元" % (plan["price"], plan["ad_budget"]),
    }


def build_decision_card(options, resolver_id, goals):
    """构建飞书决策看板卡片 (1.0 卡片格式, 与既有审批卡片同构)

    按钮 value: {"action": "choose_option", "choice": "A", "resolver_id": ...}
    """
    goal_line = "、".join(GOAL_LABELS.get(g, g) for g in goals)
    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**检测到多目标冲突**: %s\n帕累托前沿已算清，最终权衡交给您。" % goal_line,
            },
        },
    ]
    for choice, opt in options.items():
        score_txt = " / ".join(
            "%s %s" % (GOAL_LABELS.get(g, g), opt["scores"].get(g, "-"))
            for g in goals
        )
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**方案 %s：%s**\n价格 %.2f 元 | 预算 %.0f 元\n%s\n（模拟利润 %.0f 元，销量 %.0f 件）"
                % (choice, opt["label"], opt["price"], opt["ad_budget"],
                   score_txt, opt["profit"], opt["demand"]),
            },
        })
    buttons = [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "选择方案 %s：%s" % (choice, opt["label"])},
            "type": "primary" if choice == "A" else "default",
            "value": {"action": "choose_option", "choice": choice, "resolver_id": resolver_id},
        }
        for choice, opt in options.items()
    ]
    elements.append({"tag": "action", "actions": buttons})
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "⚖️ 多目标冲突仲裁 - 决策看板"},
            "template": "purple",
        },
        "elements": elements,
    }


class ConflictResolver:
    """仲裁器: resolve() 生成决策看板; apply_choice() 在用户点选后走执行器"""

    def __init__(self, verifier=None):
        self._sessions = {}
        self._lock = threading.Lock()
        self._verifier = verifier  # 懒绑定, 避免 import 期初始化 Mock 后端

    def resolve(self, user_input, ctx=None, conversation_id=""):
        """主入口: 返回决策看板结构 (含 resolver_id 与 A/B 方案)

        ctx 缺省时使用 OPTIMIZER_CONFIG 默认上下文。
        conversation_id 记入会话, 供用户点选后回推执行回执。
        """
        goals = detect_conflicts(user_input)
        if not is_conflicted(goals, user_input):
            return {"type": "no_conflict", "data": {"goals": goals}}

        cfg = OPTIMIZER_CONFIG
        ctx = ctx or {
            "current_price": cfg["default_price"],
            "competitor_price": cfg["default_competitor_price"],
            "inventory": cfg["default_inventory"],
            "ad_budget": cfg["default_ad_budget"],
        }
        plans = enumerate_grid(ctx)
        scores = score_goals(goals, plans, ctx)

        # 帕累托前沿 (所有目标维度最大化)
        points = [tuple(scores[g][i] for g in goals) for i in range(len(plans))]
        front_idx = pareto_front(points)
        logger.info("[conflict] goals=%s grid=%d pareto_front=%d",
                    goals, len(plans), len(front_idx))

        # 从前沿取代表方案 (与检测到的目标集解耦, 保证语义稳定):
        # A=激进获客(前沿上销量最大), B=稳健保利(前沿上确定性利润最大)
        idx_a = max(front_idx, key=lambda i: plans[i]["demand"])
        idx_b = max(front_idx, key=lambda i: plans[i]["profit"])
        # 若两方案重合 (退化前沿), A 取预算最省的兜底
        if idx_a == idx_b:
            idx_a = min(front_idx, key=lambda i: plans[i]["ad_budget"])

        options = {}
        for choice, idx, label in [
            ("A", idx_a, "激进获客"), ("B", idx_b, "稳健保利"),
        ]:
            plan = plans[idx]
            options[choice] = {
                "label": label,
                "price": plan["price"],
                "ad_budget": plan["ad_budget"],
                "profit": round(plan["profit"], 1),
                "demand": round(plan["demand"], 1),
                "scores": {g: scores[g][idx] for g in goals},
                "execution_request": _build_execution_request(plan, ctx),
            }

        resolver_id = uuid.uuid4().hex[:12]
        card = build_decision_card(options, resolver_id, goals)
        with self._lock:
            self._sessions[resolver_id] = {
                "goals": goals, "options": options, "ctx": ctx,
                "conversation_id": conversation_id,
            }
        logger.warning("[conflict] session=%s created, waiting for human choice", resolver_id)
        return {
            "type": "conflict_decision",
            "data": {
                "resolver_id": resolver_id,
                "goals": goals,
                "options": options,
                "card": card,
                "response": "⚖️ 检测到 %d 个冲突目标（%s），已生成帕累托决策看板，请点选方案。"
                            % (len(goals), "、".join(GOAL_LABELS.get(g, g) for g in goals)),
            },
        }

    def apply_choice(self, resolver_id, choice, conversation_id=""):
        """用户点选后调用: 关闭会话并走 executor 审批闭环 (绝不直接执行)"""
        with self._lock:
            session = self._sessions.pop(resolver_id, None)
        if not session:
            return {"type": "error", "data": {"message": "仲裁会话不存在或已过期: %s" % resolver_id}}
        option = session["options"].get(choice)
        if not option:
            return {"type": "error", "data": {"message": "无效选项: %s" % choice}}
        conversation_id = conversation_id or session.get("conversation_id", "")

        if self._verifier is None:
            from app.executor.action_verifier import get_action_verifier
            self._verifier = get_action_verifier()
        logger.info("[conflict] user chose %s (resolver=%s), routing to executor",
                    choice, resolver_id)
        return self._verifier.verify_and_execute(
            option["execution_request"],
            conversation_id=conversation_id,
            skill_name="conflict_resolver",
            user_input="仲裁方案%s: %s" % (choice, option["label"]),
        )


# 懒加载单例
_instance = None
_instance_lock = threading.Lock()


def get_conflict_resolver() -> ConflictResolver:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = ConflictResolver()
        return _instance
