# -*- coding: utf-8 -*-
"""s7 多目标冲突仲裁器测试: 冲突识别 / 归一化 / 帕累托非支配排序 / 决策看板 / 点选执行"""
import pytest

from app.optimizer.conflict_resolver import (
    CONFLICT_MIN_GOALS,
    ConflictResolver,
    build_decision_card,
    detect_conflicts,
    enumerate_grid,
    is_conflicted,
    normalize_scores,
    pareto_front,
    score_goals,
)


# ---------- 冲突识别 ----------
def test_detect_three_conflicting_goals():
    goals = detect_conflicts("帮我想个办法：省预算 + 保销量 + 清库存")
    assert {"budget", "sales", "inventory"} <= set(goals)
    assert is_conflicted(goals) is True


def test_detect_profit_sales_inventory():
    goals = detect_conflicts("既要保利润，又要冲量，还得清库存")
    assert len(goals) >= 3
    assert is_conflicted(goals)


def test_single_goal_not_conflicted():
    goals = detect_conflicts("帮我看看怎么保利润")
    assert goals == ["profit"]
    assert is_conflicted(goals) is False


def test_conflict_threshold_is_three():
    """指令约束: 超过 2 个冲突指标才启动仲裁"""
    assert CONFLICT_MIN_GOALS == 3
    assert is_conflicted(["profit", "sales"]) is False


# ---------- 归一化 ----------
def test_normalize_scores_bounds():
    s = normalize_scores([10, 20, 30])
    assert s == [0.0, 50.0, 100.0]


def test_normalize_scores_equal_values():
    assert normalize_scores([5, 5, 5]) == [100.0, 100.0, 100.0]


# ---------- 帕累托非支配排序 ----------
def test_pareto_front_simple():
    # 点0被点1支配(1,1)->(2,2); 点2(3,0)与点1互不支配
    points = [(1, 1), (2, 2), (3, 0)]
    front = pareto_front(points)
    assert sorted(front) == [1, 2]


def test_pareto_front_all_nondominated():
    points = [(3, 0), (0, 3), (1, 1)]
    front = pareto_front(points)
    assert sorted(front) == [0, 1, 2]


def test_pareto_front_single_point():
    assert pareto_front([(5, 5)]) == [0]


def test_pareto_front_minimize_mode():
    points = [(1, 1), (2, 2)]
    assert pareto_front(points, maximize=False) == [0]


# ---------- 网格与打分 ----------
def test_grid_scores_cover_all_goals():
    goals = ["profit", "sales", "budget", "inventory"]
    plans = enumerate_grid({}, price_steps=5, budget_steps=5)
    assert len(plans) == 25
    scores = score_goals(goals, plans, {})
    for g in goals:
        assert len(scores[g]) == 25
        assert 0.0 <= min(scores[g]) and max(scores[g]) <= 100.0


def test_budget_score_prefers_lower_spend():
    plans = enumerate_grid({}, price_steps=3, budget_steps=3)
    scores = score_goals(["budget"], plans, {})
    budgets = [p["ad_budget"] for p in plans]
    min_b = min(budgets)
    assert scores["budget"][budgets.index(min_b)] == 100.0


# ---------- resolve 全流程 ----------
def test_resolve_returns_decision_board():
    resolver = ConflictResolver()
    result = resolver.resolve("省预算 + 保销量 + 清库存，帮我权衡")
    assert result["type"] == "conflict_decision"
    data = result["data"]
    assert set(data["options"].keys()) == {"A", "B"}
    assert data["options"]["A"]["label"] == "激进获客"
    assert data["options"]["B"]["label"] == "稳健保利"
    assert data["resolver_id"]

    # A 激进获客: 预估销量 >= B; B 稳健保利: 预估利润 >= A (语义与目标集解耦)
    assert data["options"]["A"]["demand"] >= data["options"]["B"]["demand"]
    assert data["options"]["B"]["profit"] >= data["options"]["A"]["profit"]
    # 两方案分数都在 0-100 区间
    for opt in data["options"].values():
        assert all(0.0 <= v <= 100.0 for v in opt["scores"].values())


def test_resolve_no_conflict_short_circuit():
    resolver = ConflictResolver()
    result = resolver.resolve("帮我分析下销量")
    assert result["type"] == "no_conflict"


def test_decision_card_structure():
    options = {
        "A": {"label": "激进获客", "price": 90, "ad_budget": 1200,
              "profit": 70.0, "demand": 95.0, "scores": {"profit": 70, "sales": 95},
              "execution_request": {}},
        "B": {"label": "稳健保利", "price": 108, "ad_budget": 500,
              "profit": 95.0, "demand": 70.0, "scores": {"profit": 95, "sales": 70},
              "execution_request": {}},
    }
    card = build_decision_card(options, "rid-123", ["profit", "sales"])
    assert card["header"]["title"]["content"].startswith("⚖️")
    actions = card["elements"][-1]
    assert actions["tag"] == "action"
    values = [b["value"] for b in actions["actions"]]
    assert {"action": "choose_option", "choice": "A", "resolver_id": "rid-123"} in values
    assert {"action": "choose_option", "choice": "B", "resolver_id": "rid-123"} in values


# ---------- apply_choice 点选后走执行器审批 ----------
def test_apply_choice_routes_to_approval():
    resolver = ConflictResolver()
    result = resolver.resolve("省预算 + 保销量 + 清库存")
    rid = result["data"]["resolver_id"]

    verify_result = resolver.apply_choice(rid, "A", conversation_id="conv-conflict")
    assert verify_result["type"] == "approval_required"
    assert verify_result["data"]["approval_id"]
    # 会话一次性消费
    assert resolver.apply_choice(rid, "A")["type"] == "error"


def test_apply_choice_invalid_option():
    resolver = ConflictResolver()
    result = resolver.resolve("省预算 + 保销量 + 清库存")
    rid = result["data"]["resolver_id"]
    assert resolver.apply_choice(rid, "C")["type"] == "error"
